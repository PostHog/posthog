// Flags a PR mixing Python or frontend lanes with Node or Rust lanes, which makes
// queued Node and Rust PRs behind it run the slow suites. Files whose own rule
// spans both sides (protos, universal tripwires) are ignored.

const { computeTargets } = require('./trunk-impacted-targets')

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
    const heavyFiles = []
    const lightFiles = []
    for (const file of changedFiles) {
        let targets
        try {
            targets = computeTargets([file], context)
        } catch {
            return null
        }
        // ALL means unknown, not both sides.
        if (!Array.isArray(targets)) {
            continue
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
