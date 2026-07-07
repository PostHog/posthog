#!/usr/bin/env node

// Adds team/feature labels to a PR based on its conventional-commit scope
// (`type(scope): summary`). Additive only — it never removes labels, so manual
// labels and the ownership-based labeler (assign-reviewers.js) are left intact.
//
// The scope -> labels mapping lives in .github/auto-assign-labels.json, OUTSIDE
// this script, so the owning team can adjust mappings without changing (and
// re-approving) the workflow or this script. The config is read from the master
// checkout, never the PR, so a fork PR can't inject its own mappings, and the
// PR title only ever selects from a fixed, pre-approved set of labels.

const fs = require('fs')
const path = require('path')

// Anchored to this script's location, not the cwd, so it resolves the same
// whether the workflow runs `node .github/scripts/…` from the repo root or a
// test invokes it from elsewhere.
const DEFAULT_CONFIG_PATH = path.join(__dirname, '..', 'auto-assign-labels.json')

function loadRules(configPath = process.env.CONFIG_PATH || DEFAULT_CONFIG_PATH) {
    if (!fs.existsSync(configPath)) {
        throw new Error(`No label config found at "${configPath}"`)
    }
    const parsed = JSON.parse(fs.readFileSync(configPath, 'utf8'))
    return Array.isArray(parsed.rules) ? parsed.rules : []
}

// Pull the scope tokens out of a conventional-commit subject: `type(scope): …`.
// Requires the trailing colon so stray parentheses in prose don't match.
// Supports comma-separated scopes (`feat(flags,cohorts):`) and is case-insensitive.
function parseScopes(title) {
    const match = /^\s*\w+\(([^)]+)\)!?:/.exec(title || '')
    if (!match) {
        return []
    }
    return match[1]
        .split(',')
        .map((scope) => scope.trim().toLowerCase())
        .filter(Boolean)
}

// Map a title's scopes to the de-duplicated labels they should carry.
function labelsForTitle(title, rules) {
    const scopes = new Set(parseScopes(title))
    const labels = new Set()

    for (const rule of rules) {
        if ((rule.scopes || []).some((scope) => scopes.has(String(scope).toLowerCase()))) {
            for (const label of rule.labels || []) {
                labels.add(label)
            }
        }
    }

    return Array.from(labels)
}

// Best-effort: a labeling failure must never fail the job. The workflow does
// nothing but label, so a hard failure would only paint a non-blocking red ✗ on
// the PR over a transient blip or config drift (e.g. a renamed label). We warn
// loudly instead so the cause is visible in the Actions log.
async function addLabels(labels) {
    const { GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER } = process.env

    if (labels.length === 0) {
        console.info('ℹ️  Title has no labelable scope; nothing to do')
        return
    }

    console.info(`Adding labels: ${labels.join(', ')}`)

    try {
        // Idempotent: GitHub keeps labels already present, so re-runs on title
        // edits are safe. Additive — we never strip labels that no longer match.
        const response = await fetch(`https://api.github.com/repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/labels`, {
            method: 'POST',
            headers: {
                Authorization: `token ${GITHUB_TOKEN}`,
                Accept: 'application/vnd.github.v3+json',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ labels }),
        })

        if (!response.ok) {
            console.warn(
                `⚠️  Could not apply labels: ${response.status} ${response.statusText}\n${await response.text()}`
            )
            return
        }

        console.info('✅ Labels applied')
    } catch (error) {
        // A non-Error throw has no `.message`; fall back to the value itself so
        // the real reason still surfaces in the log.
        console.warn(`⚠️  Skipping labels: ${error?.message ?? error}`)
    }
}

async function main() {
    const { GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER, PR_TITLE } = process.env
    const missing = Object.entries({ GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER })
        .filter(([, value]) => !value)
        .map(([name]) => name)

    if (missing.length > 0) {
        console.error(`Missing required environment variables: ${missing.join(', ')}`)
        process.exit(1)
    }

    try {
        const rules = loadRules()
        const labels = labelsForTitle(PR_TITLE, rules)
        console.info(`PR title: ${PR_TITLE || '(empty)'}`)
        await addLabels(labels)
    } catch (error) {
        console.error('Error:', error?.message ?? error)
        process.exit(1)
    }
}

if (require.main === module) {
    main()
}

module.exports = { parseScopes, labelsForTitle, loadRules }
