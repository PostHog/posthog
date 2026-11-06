// Flags a PR mixing Python or frontend lanes with Node or Rust lanes, which makes
// queued Node and Rust PRs behind it run the slow suites. Files whose own rule
// spans both sides (protos) and all tripwires are ignored.

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
    let unclassified = false
    for (const file of changedFiles) {
        // Tripwires are workflows and tool settings, and the warning is about code.
        if (isTripwire(file)) {
            continue
        }
        const targets = laneTargets(file, context, universe)
        if (!targets) {
            unclassified = true
            continue
        }
        const side = sideOf(targets)
        if (side === 'heavy') {
            heavyFiles.push(file)
        } else if (side === 'light') {
            lightFiles.push(file)
        }
    }
    const mixed = heavyFiles.length > 0 && lightFiles.length > 0
    // An unclassified file can add a side but not remove one, so a proven mix holds.
    if (unclassified && !mixed) {
        return null
    }
    return { mixed, heavyFiles, lightFiles }
}

/** Null when the lane rules name no side for the file. */
function laneTargets(file, context, universe) {
    let targets
    try {
        targets = computeTargets([file], context)
    } catch (error) {
        console.error(`Could not classify ${file} by lane side (${error.message}); it counts on neither side`)
        return null
    }
    // ALL means the rules could not enumerate the lanes of this file.
    if (!Array.isArray(targets)) {
        console.error(`Could not enumerate the lanes of ${file}; it counts on neither side`)
        return null
    }
    // Every lane is the unknown-path fallback or a deliberate widening. Neither names a side.
    if (universe && targets.length >= universe.length) {
        console.error(`${file} claims every lane; it counts on neither side`)
        return null
    }
    return targets
}

module.exports = { crossLaneFiles, sideOf, MAX_FILES }
