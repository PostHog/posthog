// Flags a PR that claims a Python or frontend lane and a Node or Rust lane: the
// queue tests each PR on top of those ahead in its lane, so every Node or Rust PR
// behind it would run the Django and frontend suites too.
//
// Files are classified one at a time by the lane rules themselves. A file whose
// own rule spans both sides (a proto, a universal tripwire) is cross-lane by
// design and is ignored.

const { computeTargets } = require('./trunk-impacted-targets')

const HEAVY_PREFIXES = ['py:', 'fe:']
const LIGHT_PREFIXES = ['node:', 'rust:']

// Classifying is one rule pass per file. A change set this large is a mass move
// or a generated rewrite, where a verdict would be noise.
const MAX_FILES = 1000

function sideOf(targets) {
    const heavy = targets.some((target) => HEAVY_PREFIXES.some((prefix) => target.startsWith(prefix)))
    const light = targets.some((target) => LIGHT_PREFIXES.some((prefix) => target.startsWith(prefix)))
    return heavy && light ? 'both' : heavy ? 'heavy' : light ? 'light' : 'neither'
}

/**
 * Returns `null` when no verdict can be given (too many files, or the rules
 * could not run), otherwise which files hold each side.
 */
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
        // The ALL sentinel means the rules could not enumerate anything, which
        // says nothing about which side this file is on.
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
