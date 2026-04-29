'use strict'

// Read-only access to the feature-flags canary block in PostHog/charts:state.yaml
// plus a phase resolver and a small async polling helper. We avoid pulling in a
// YAML parser by extracting the canary block via a targeted regex — state.yaml
// is sort_keys'd and the block has a stable, scalar-only shape.

const CHARTS_OWNER = 'PostHog'
const CHARTS_REPO = 'charts'
const CHARTS_STATE_PATH = 'state.yaml'

function parseScalar(raw) {
    if (raw === undefined || raw === null) return null
    const v = String(raw).trim()
    if (v === '' || v === 'null' || v === '~') return null
    if (v === 'true') return true
    if (v === 'false') return false
    if (/^-?\d+$/.test(v)) return parseInt(v, 10)
    if (/^-?\d+\.\d+$/.test(v)) return parseFloat(v)
    const dq = v.match(/^"(.*)"$/)
    if (dq) return dq[1]
    const sq = v.match(/^'(.*)'$/)
    if (sq) return sq[1]
    return v
}

// Extract `state.feature-flags.canary` from a state.yaml string. Returns
// null if the block is missing. state.yaml is normalized via
// `yq sort_keys(...)` so feature-flags sits at indent 2, canary at indent 4,
// fields at indent 6 — a simple line walker is robust across whatever else
// the file may contain.
function parseCanaryBlock(yaml) {
    if (!yaml || typeof yaml !== 'string') return null
    const lines = yaml.split(/\r?\n/)
    let inFeatureFlags = false
    let inCanary = false
    const fields = {}
    for (const line of lines) {
        if (/^state:\s*$/.test(line)) continue
        const m = line.match(/^( *)([^\s:#][^:]*):\s*(.*)$/)
        if (!m) continue
        const indent = m[1].length
        const key = m[2].trim()
        const value = m[3]
        if (indent === 2) {
            inFeatureFlags = key === 'feature-flags'
            inCanary = false
            continue
        }
        if (inFeatureFlags && indent === 4) {
            inCanary = key === 'canary'
            continue
        }
        if (inCanary && indent === 6) {
            fields[key] = parseScalar(value)
        }
    }
    return Object.keys(fields).length ? fields : null
}

async function readChartsState({ octokit, ref = 'main' }) {
    const { data } = await octokit.rest.repos.getContent({
        owner: CHARTS_OWNER,
        repo: CHARTS_REPO,
        path: CHARTS_STATE_PATH,
        ref,
    })
    if (!data || Array.isArray(data) || !data.content) return null
    const yaml = Buffer.from(data.content, data.encoding || 'base64').toString('utf8')
    return parseCanaryBlock(yaml)
}

// Translate (state.yaml + charts workflow run) into a phase. Used by the
// watcher to decide whether to update the comment and when to stop polling.
function derivePhase(state, chartsRun, prNumber) {
    const pr = parseInt(prNumber, 10)
    const enabled = !!(state && state.enabled === true)
    const owns = enabled && state.pr_number === pr

    if (!enabled) return 'EXPIRED'
    if (!owns) return 'EXPIRED'

    const status = chartsRun?.status || null
    const conclusion = chartsRun?.conclusion || null
    if (status === 'completed') {
        if (conclusion === 'success') return 'HEALTHY'
        if (conclusion === 'cancelled') return 'CANCELED'
        return 'FAILED'
    }

    const weight = state.weight ?? 0
    return weight > 0 ? 'ROUTING' : 'ROLLING_OUT'
}

async function pollUntil({ predicate, timeoutMs, intervalMs }) {
    const start = Date.now()
    // Run once immediately so a fast-completing rollout isn't delayed by
    // the first sleep.
    if (await predicate()) return true
    while (Date.now() - start < timeoutMs) {
        await new Promise((res) => setTimeout(res, intervalMs))
        if (await predicate()) return true
    }
    return false
}

module.exports = {
    CHARTS_OWNER,
    CHARTS_REPO,
    CHARTS_STATE_PATH,
    parseScalar,
    parseCanaryBlock,
    readChartsState,
    derivePhase,
    pollUntil,
}
