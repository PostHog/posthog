// Polls GitHub's /rate_limit endpoint and emits one PostHog event per resource.
//
// The default github-script auth is the workflow's $GITHUB_TOKEN, so the snapshot
// reflects this repository's per-repo bucket — the slice that GitHub's org-level
// API Insights dashboard does not surface (search, graphql, code_search included
// for parity even though they have separate buckets).
//
// /rate_limit calls themselves do not consume the budget they observe, so this
// monitor is safe to run on a tight cron without distorting its own measurement.

const POSTHOG_HOST = 'https://us.i.posthog.com'
const EVENT_NAME = 'github_rate_limit_observed'
const DEFAULT_SOURCE = 'github_token'

async function captureEvent({ fetchImpl, posthogToken, event, distinctId, properties, timestamp }) {
    const res = await fetchImpl(`${POSTHOG_HOST}/capture/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            api_key: posthogToken,
            event,
            distinct_id: distinctId,
            properties,
            timestamp,
        }),
    })
    if (!res.ok) {
        const body = await res.text().catch(() => '')
        throw new Error(`capture ${res.status}: ${body.slice(0, 200)}`)
    }
}

// The workflow runs on every PR open/synchronize and master push, so each sample
// can be attributed to the event that triggered it. Capturing that context turns
// the aggregate /rate_limit series into a per-trigger breakdown downstream in
// PostHog — which event types and PR sizes precede the steepest core burn.
function buildTrigger(context) {
    const payload = context.payload || {}
    const pr = payload.pull_request || null
    const num = (value) => (typeof value === 'number' ? value : null)
    // PR head refs are short (`feature/foo`); push refs are qualified
    // (`refs/heads/master`). Normalize to the short form so the column is uniform.
    const ref = pr?.head?.ref ?? payload.ref ?? null
    return {
        trigger_event: context.eventName || null,
        trigger_action: payload.action || null,
        head_ref: ref ? ref.replace(/^refs\/heads\//, '') : null,
        pr_number: num(pr?.number),
        pr_author: pr?.user?.login ?? null,
        pr_changed_files: num(pr?.changed_files),
        pr_additions: num(pr?.additions),
        pr_deletions: num(pr?.deletions),
    }
}

// `source` identifies which rate-limit bucket the snapshot came from: the
// per-repo default GITHUB_TOKEN, or a dedicated GitHub App installation bucket
// (e.g. posthog-devex-general, the setup-action offload bucket). The two are
// separate 15k buckets, so downstream they're a per-bucket time series.
function buildProperties({ resource, snapshot, observedAt, observedAtSeconds, repo, runId, trigger, source = DEFAULT_SOURCE }) {
    const used = typeof snapshot.used === 'number' ? snapshot.used : snapshot.limit - snapshot.remaining
    const utilization = snapshot.limit > 0 ? used / snapshot.limit : 0
    return {
        repo,
        resource,
        used,
        remaining: snapshot.remaining,
        limit: snapshot.limit,
        utilization,
        reset_at: new Date(snapshot.reset * 1000).toISOString(),
        reset_in_seconds: Math.max(0, snapshot.reset - observedAtSeconds),
        source,
        observed_at: observedAt,
        workflow_run_id: runId || null,
        ...trigger,
    }
}

module.exports = async ({ github, context, core }, { now: _now, fetch: _fetch, source: _source } = {}) => {
    const source = _source || DEFAULT_SOURCE
    const fetchImpl = _fetch || fetch
    const observedAtDate = _now ? _now() : new Date()
    const observedAt = observedAtDate.toISOString()
    const observedAtSeconds = Math.floor(observedAtDate.getTime() / 1000)
    const repo = `${context.repo.owner}/${context.repo.repo}`
    const runId = process.env.GITHUB_RUN_ID || null
    const trigger = buildTrigger(context)

    const posthogToken = process.env.POSTHOG_DEVEX_PROJECT_API_TOKEN
    if (!posthogToken) {
        core.warning('POSTHOG_DEVEX_PROJECT_API_TOKEN not set; nothing to emit')
        core.setOutput('emitted', '0')
        core.setOutput('failures', '0')
        return
    }

    const { data } = await github.rest.rateLimit.get()
    const resources = data?.resources || {}

    let emitted = 0
    let failures = 0
    for (const [resource, snapshot] of Object.entries(resources)) {
        if (!snapshot || typeof snapshot.limit !== 'number' || typeof snapshot.remaining !== 'number') {continue}
        const properties = buildProperties({ resource, snapshot, observedAt, observedAtSeconds, repo, runId, trigger, source })
        core.info(`[${source}] ${resource}: ${properties.remaining}/${properties.limit} remaining (resets ${properties.reset_at})`)
        try {
            await captureEvent({
                fetchImpl,
                posthogToken,
                event: EVENT_NAME,
                distinctId: repo,
                properties,
                timestamp: observedAt,
            })
            emitted++
        } catch (err) {
            failures++
            core.warning(`Failed to emit ${resource}: ${err.message}`)
        }
    }

    core.info(`Emitted ${emitted} event(s); ${failures} failure(s)`)
    core.setOutput('emitted', String(emitted))
    core.setOutput('failures', String(failures))
}

module.exports.buildProperties = buildProperties
module.exports.buildTrigger = buildTrigger
module.exports.captureEvent = captureEvent
