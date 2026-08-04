#!/usr/bin/env node

// Builds the property bag for the `trunk_lane_targets` event from a PR's
// changed files and the target set trunk-impacted-targets.js computed for them.
//
// WHAT THIS MEASURES: the cost side of lane assignment — how often a PR widens,
// which rule widened it, and how many lanes it ends up claiming. It cannot
// measure the safety side. A lane is wrong when two conflicting PRs get
// disjoint targets and merge in parallel, and neither the file list nor the
// target set can show that; it takes Trunk's record of what actually ran
// together plus master's post-merge result. Read a falling lane count as
// cheaper queueing, never as evidence the rules are correct.
//
// Raw paths are deliberately not sent. A PR can touch thousands of them, they
// blow past property limits, and in aggregate the directory histogram answers
// the same questions. The exception is tripwire_files, which names the handful
// of paths that forced ALL, because that is the field that says which rule to
// go tune.
//
// Input:  changed file paths, one per line, on stdin
//         IMPACTED_TARGETS — the JSON uploaded to Trunk, {"impactedTargets": ...}
// Output: JSON object of event properties on stdout

const fs = require('fs')
const { isTripwire } = require('./trunk-impacted-targets')

// Enough to name the culprit without turning a wide PR into a huge payload.
const MAX_LISTED = 20

function domainOf(target) {
    const prefix = target.split(':')[0]
    return ['py', 'fe', 'rust', 'svc', 'node', 'tools', 'agents', 'prose'].includes(prefix) ? prefix : 'other'
}

function buildProperties(changedFiles, impactedTargets) {
    const isAll = impactedTargets === 'ALL'
    const targets = Array.isArray(impactedTargets) ? impactedTargets : []
    const isProse = targets.length === 1 && targets[0] === 'prose'

    const targetDomains = {}
    for (const target of targets) {
        const domain = domainOf(target)
        targetDomains[domain] = (targetDomains[domain] || 0) + 1
    }

    const topDirs = {}
    const products = new Set()
    for (const file of changedFiles) {
        const segments = file.split('/')
        topDirs[segments[0]] = (topDirs[segments[0]] || 0) + 1
        if (segments[0] === 'products' && segments.length > 1) {
            products.add(segments[1])
        }
    }

    const tripwireFiles = changedFiles.filter(isTripwire)

    return {
        changed_file_count: changedFiles.length,
        changed_top_dirs: topDirs,
        changed_products: [...products].sort().slice(0, MAX_LISTED),
        changed_product_count: products.size,
        is_all: isAll,
        is_prose: isProse,
        target_count: targets.length,
        targets: targets.slice(0, MAX_LISTED),
        target_domains: targetDomains,
        tripwire_files: tripwireFiles.slice(0, MAX_LISTED),
        // Separates the three ways a PR ends up in one lane: a rule that
        // deliberately widened it, a path no rule claimed (the early warning
        // that the script needs a rule for a directory someone just added), and
        // the degraded case where the diff itself failed and the file list
        // never reached the script.
        widening_reason: !isAll
            ? null
            : changedFiles.length === 0
              ? 'diff_unavailable'
              : tripwireFiles.length > 0
                ? 'tripwire'
                : 'unclassified_path',
    }
}

module.exports = { buildProperties }

if (require.main === module) {
    const changedFiles = fs
        .readFileSync(0, 'utf8')
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
    let impactedTargets
    try {
        impactedTargets = JSON.parse(process.env.IMPACTED_TARGETS || '{}').impactedTargets
    } catch (error) {
        console.error(`Could not read IMPACTED_TARGETS (${error.message}); reporting the file side only`)
    }
    process.stdout.write(JSON.stringify(buildProperties(changedFiles, impactedTargets)))
}
