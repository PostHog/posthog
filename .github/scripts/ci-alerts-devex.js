// Master CI Alerts - Cron-based rolling window alert for sustained master failures
//
// Polls the GitHub API every 5 minutes to check the latest completed run of each
// watched workflow on master. Only alerts when master has been continuously broken
// for ALERT_THRESHOLD_MINUTES (default 30), filtering out transient flakes.
//
// Also checks GitHub API rate limits proactively — if remaining quota is critically
// low, alerts independently so the team knows CI monitoring may be blind.
//
// State structure (persisted via GitHub Actions cache as .alerts-devex):
// {
//   failing: { [workflow]: { since: ISO string, sha: string, run_url: string, workflow_file: string } },
//   alerted: boolean,
//   slack_ts: string | null,
//   slack_channel: string | null,
//   last_failing_list: string,   // comma-separated, used to detect changes for UPDATE
//   resolved: boolean,
//   rate_limit_alerted: boolean,
//   rate_limit_slack_ts: string | null,
//   rate_limit_slack_channel: string | null,
// }

const STATE_FILE = '.alerts-devex'

async function checkRateLimit(github) {
    const { data } = await github.rest.rateLimit.get()
    const { remaining, limit, reset } = data.resources.core
    const thresholdPercent = parseInt(process.env.RATE_LIMIT_THRESHOLD_PERCENT || '10', 10)
    const critical = remaining < limit * (thresholdPercent / 100)
    return { remaining, limit, reset, critical }
}

function determineRateLimitAction(state, critical) {
    const wasAlerted = state?.rate_limit_alerted === true
    if (critical && !wasAlerted) return 'create'
    if (!critical && wasAlerted) return 'resolve'
    return 'none'
}

async function fetchWorkflowStatus(github, owner, repo, workflowFile) {
    const { data } = await github.rest.actions.listWorkflowRuns({
        owner,
        repo,
        workflow_id: workflowFile,
        branch: 'master',
        event: 'push',
        per_page: 1,
        status: 'completed',
    })

    const run = data.workflow_runs[0]
    if (!run) return null

    return {
        name: run.name,
        conclusion: run.conclusion,
        sha: run.head_sha,
        run_url: run.html_url,
        updated_at: run.updated_at,
        workflow_file: workflowFile,
    }
}

function updateFailingMap(failing, workflows) {
    const updated = { ...failing }

    for (const wf of workflows) {
        if (!wf) continue

        if (wf.conclusion === 'failure' || wf.conclusion === 'timed_out') {
            if (!updated[wf.name]) {
                // New failure — use the run's timestamp, not observation time,
                // so the clock survives state loss (cache eviction, etc.)
                updated[wf.name] = {
                    since: wf.updated_at,
                    sha: wf.sha,
                    run_url: wf.run_url,
                    workflow_file: wf.workflow_file,
                }
            } else {
                // Still failing — update sha/url but keep the original since
                updated[wf.name] = {
                    ...updated[wf.name],
                    sha: wf.sha,
                    run_url: wf.run_url,
                    workflow_file: wf.workflow_file,
                }
            }
        } else if (wf.conclusion === 'success') {
            delete updated[wf.name]
        }
        // Ignore cancelled, skipped, etc. — leave state unchanged
    }

    return updated
}

function getOldestFailingSince(failing) {
    const times = Object.values(failing).map((f) => new Date(f.since).getTime())
    return times.length > 0 ? Math.min(...times) : null
}

function determineAction(state, failing, thresholdMs, now) {
    const failingNames = Object.keys(failing).sort()
    const failingList = failingNames.join(', ')
    const hasFailures = failingNames.length > 0
    const wasAlerted = state?.alerted === true

    if (!hasFailures && !wasAlerted) {
        return { action: 'none', failingList, save: true }
    }

    if (!hasFailures && wasAlerted) {
        return { action: 'resolve', failingList, save: true }
    }

    const oldest = getOldestFailingSince(failing)
    const elapsed = now.getTime() - oldest
    const thresholdReached = elapsed >= thresholdMs

    if (!thresholdReached) {
        // Under threshold — save state but don't alert
        return { action: 'none', failingList, save: true }
    }

    if (!wasAlerted) {
        return { action: 'create', failingList, save: true }
    }

    // Already alerted — check if the failing set changed
    const previousList = state.last_failing_list || ''
    if (failingList !== previousList) {
        return { action: 'update', failingList, save: true }
    }

    return { action: 'none', failingList, save: false }
}

module.exports = async ({ github, context, core }, { fs: _fs, now: _now } = {}) => {
    const fs = _fs || require('fs')
    const now = _now || new Date()

    const owner = context.repo.owner
    const repo = context.repo.repo

    const workflowFiles = (process.env.WATCHED_WORKFLOWS || '').split(',').filter(Boolean)
    const criticalWorkflows = new Set((process.env.CRITICAL_WORKFLOWS || '').split(',').filter(Boolean))
    const thresholdMinutes = parseInt(process.env.ALERT_THRESHOLD_MINUTES || '30', 10)
    const thresholdMs = thresholdMinutes * 60 * 1000

    // Load existing state
    let state = null
    if (fs.existsSync(STATE_FILE)) {
        try {
            const raw = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'))
            if (raw.resolved) {
                console.log('Found resolved incident, treating as no active state')
                state = {
                    failing: {},
                    rate_limit_alerted: raw.rate_limit_alerted ?? false,
                    rate_limit_slack_ts: raw.rate_limit_slack_ts ?? null,
                    rate_limit_slack_channel: raw.rate_limit_slack_channel ?? null,
                }
            } else {
                state = { failing: {}, ...raw }
                console.log('Loaded existing state')
            }
        } catch (e) {
            console.log('Failed to parse state file, treating as fresh')
        }
    }

    // Check rate limits before polling workflows
    let rateLimit = null
    let rateLimitAction = 'none'
    try {
        rateLimit = await checkRateLimit(github)
        console.log(`Rate limit: ${rateLimit.remaining}/${rateLimit.limit} remaining`)
        rateLimitAction = determineRateLimitAction(state, rateLimit.critical)
    } catch (err) {
        console.log(`Failed to check rate limit: ${err.message}`)
    }

    // Fetch latest run for each watched workflow
    console.log(`Checking ${workflowFiles.length} workflows...`)
    const results = await Promise.all(
        workflowFiles.map((wf) =>
            fetchWorkflowStatus(github, owner, repo, wf).catch((err) => {
                console.log(`Failed to fetch ${wf}: ${err.message}`)
                return null
            })
        )
    )

    for (const r of results) {
        if (r) console.log(`  ${r.name}: ${r.conclusion}`)
    }

    // Update failing map
    const previousFailing = state?.failing || {}
    const failing = updateFailingMap(previousFailing, results)

    // Determine action
    const { action, failingList, save } = determineAction(state, failing, thresholdMs, now)

    console.log(`Action: ${action}`)
    console.log(`Failing: ${failingList || 'none'}`)

    // Build new state
    const saveRateLimit = rateLimitAction !== 'none'
    const newState = {
        failing,
        alerted: action === 'create' || (state?.alerted === true && action !== 'resolve'),
        slack_ts: state?.slack_ts || null,
        slack_channel: state?.slack_channel || null,
        last_failing_list: failingList,
        resolved: action === 'resolve',
        rate_limit_alerted:
            rateLimitAction === 'create' || (state?.rate_limit_alerted === true && rateLimitAction !== 'resolve'),
        rate_limit_slack_ts: state?.rate_limit_slack_ts || null,
        rate_limit_slack_channel: state?.rate_limit_slack_channel || null,
    }

    if (save || saveRateLimit) {
        fs.writeFileSync(STATE_FILE, JSON.stringify(newState, null, 2))
    }

    // Set outputs for the workflow
    core.setOutput('action', action)
    core.setOutput('save_cache', save || saveRateLimit ? 'true' : 'false')
    core.setOutput('delete_old_caches', action === 'create' ? 'true' : 'false')
    core.setOutput('failing_workflows', failingList)
    core.setOutput('failing_count', String(Object.keys(failing).length))

    // For Slack messages
    if (action === 'create' || action === 'update') {
        const oldest = getOldestFailingSince(failing)
        const mins = Math.round((now.getTime() - oldest) / 60000)
        core.setOutput('duration_mins', String(mins))

        // Build run links for Slack, split by severity
        const blocking = []
        const nonBlocking = []
        for (const [name, info] of Object.entries(failing)) {
            const link = `<${info.run_url}|${name}>`
            if (info.workflow_file && criticalWorkflows.has(info.workflow_file)) {
                blocking.push(link)
            } else {
                nonBlocking.push(link)
            }
        }
        core.setOutput('failing_links', [...blocking, ...nonBlocking].join(', '))
        core.setOutput('failing_links_blocking', blocking.join(', '))
        core.setOutput('failing_links_non_blocking', nonBlocking.join(', '))

        // Pre-formatted detail line for Slack, split by severity
        let detail = ''
        if (blocking.length > 0) detail += `*Blocking:* ${blocking.join(', ')}`
        if (nonBlocking.length > 0) {
            if (detail) detail += '\n'
            detail += `*Non-blocking:* ${nonBlocking.join(', ')}`
        }
        core.setOutput('failing_detail', detail)
    }

    if (action === 'resolve') {
        const oldest = getOldestFailingSince(previousFailing)
        const mins = oldest ? Math.round((now.getTime() - oldest) / 60000) : 0
        core.setOutput('duration_mins', String(mins))
        core.setOutput('slack_ts', state?.slack_ts || '')
        core.setOutput('slack_channel', state?.slack_channel || '')
    }

    if (action === 'update') {
        core.setOutput('slack_ts', state?.slack_ts || '')
        core.setOutput('slack_channel', state?.slack_channel || '')

        // Determine what changed for thread reply
        const prevNames = new Set((state?.last_failing_list || '').split(', ').filter(Boolean))
        const currNames = new Set(failingList.split(', ').filter(Boolean))
        const added = [...currNames].filter((n) => !prevNames.has(n))
        const removed = [...prevNames].filter((n) => !currNames.has(n))
        core.setOutput('added_workflows', added.join(', '))
        core.setOutput('removed_workflows', removed.join(', '))
    }

    // Rate limit outputs
    core.setOutput('rate_limit_action', rateLimitAction)
    if (rateLimit) {
        core.setOutput('rate_limit_remaining', String(rateLimit.remaining))
        core.setOutput('rate_limit_limit', String(rateLimit.limit))
        const resetMins = Math.max(0, Math.round((rateLimit.reset * 1000 - now.getTime()) / 60000))
        core.setOutput('rate_limit_reset_mins', String(resetMins))
    }
    if (rateLimitAction === 'resolve') {
        core.setOutput('rate_limit_slack_ts', state?.rate_limit_slack_ts || '')
        core.setOutput('rate_limit_slack_channel', state?.rate_limit_slack_channel || '')
    }
}
