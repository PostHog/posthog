// Flags a PR mixing Python or frontend lanes with Node or Rust lanes, which makes
// queued Node and Rust PRs behind it run the slow suites. Files whose own rule
// spans both sides (protos, universal tripwires) are ignored.

const { allKnownTargets, computeTargets, isTripwire } = require('./trunk-impacted-targets')

const HEAVY_PREFIXES = ['py:', 'fe:']
const LIGHT_PREFIXES = ['node:', 'rust:']

// Beyond this a PR is a mass move, where a verdict is noise.
const MAX_FILES = 1000

function sideOf(targets) {
    const heavy = targets.some((target) => HEAVY_PREFIXES.some((prefix) => target.startsWith(prefix)))
    const light = targets.some((target) => LIGHT_PREFIXES.some((prefix) => target.startsWith(prefix)))
    return heavy && light ? 'both' : heavy ? 'heavy' : light ? 'light' : 'neither'
}

/** Null when no verdict can be given. */
function crossLaneFiles(changedFiles, context) {
    if (changedFiles.length === 0 || changedFiles.length > MAX_FILES) {
        return null
    }
    let universe
    try {
        universe = allKnownTargets(context)
    } catch (error) {
        console.error(`Could not enumerate the lanes (${error.message}); cross_lane reports unknown`)
        return null
    }
    const heavyFiles = []
    const lightFiles = []
    for (const file of changedFiles) {
        let targets
        try {
            targets = computeTargets([file], context)
        } catch (error) {
            console.error(`Could not classify ${file} by lane side (${error.message}); cross_lane reports unknown`)
            return null
        }
        // ALL means the rules could not enumerate lanes, so no verdict holds.
        if (!Array.isArray(targets)) {
            console.error(`Could not enumerate the lanes of ${file}; cross_lane reports unknown`)
            return null
        }
        // Every lane without a tripwire is the rules' fallback for an unknown path.
        if (universe && targets.length >= universe.length && !isTripwire(file)) {
            console.error(`No lane rule claims ${file}; cross_lane reports unknown`)
            return null
        }
        const side = sideOf(targets)
        if (side === 'heavy') {
            heavyFiles.push(file)
        } else if (side === 'light') {
            lightFiles.push(file)
        }
    }
    return { mixed: heavyFiles.length > 0 && lightFiles.length > 0, heavyFiles, lightFiles }
}

module.exports = { crossLaneFiles, sideOf, MAX_FILES }
