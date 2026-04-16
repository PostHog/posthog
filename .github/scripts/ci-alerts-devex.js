// Master CI Alerts - Cron-based rolling window alert for sustained master failures
//
// Polls the GitHub API every 5 minutes to check recent completed runs of each
// watched workflow on master. Only alerts when a workflow has ALERT_THRESHOLD_RUNS
// (default 5) consecutive failures, filtering out transient flakes.
//
// Also checks GitHub API rate limits proactively — if remaining quota is critically
// low, alerts independently so the team knows CI monitoring may be blind.
//
// State structure (persisted via GitHub Actions cache as .alerts-devex):
// {
//   failing: { [workflow]: { since: ISO, sha, run_url, workflow_file, consecutive_failures } },
//   alerted: boolean,
//   slack_ts: string | null,
//   slack_channel: string | null,
//   last_failing_list: string,
//   last_failing_detail: string,  // preserved for resolve messages
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

async function fetchWorkflowRuns(github, owner, repo, workflowFile, perPage) {
    const { data } = await github.rest.actions.listWorkflowRuns({
        owner,
        repo,
        workflow_id: workflowFile,
        branch: 'master',
        event: 'push',
        per_page: perPage,
        status: 'completed',
    })

    // Filter out cancelled/skipped — only real conclusions count
    return data.workflow_runs
        .filter((run) => run.conclusion !== 'cancelled' && run.conclusion !== 'skipped')
        .map((run) => ({
            name: run.name,
            conclusion: run.conclusion,
            sha: run.head_sha,
            run_url: run.html_url,
            updated_at: run.updated_at,
            workflow_file: workflowFile,
        }))
}

function countConsecutiveFailures(runs) {
    let count = 0
    for (const run of runs) {
        if (run.conclusion === 'failure' || run.conclusion === 'timed_out') {
            count++
        } else {
            break
        }
    }
    return count
}

function buildFailingMap(allWorkflowRuns) {
    const failing = {}
    for (const runs of allWorkflowRuns) {
        if (runs.length === 0) continue
        const count = countConsecutiveFailures(runs)
        if (count > 0) {
            const latest = runs[0]
            const oldest = runs[count - 1]
            failing[latest.name] = {
                since: oldest.updated_at,
                sha: latest.sha,
                run_url: latest.run_url,
                workflow_file: latest.workflow_file,
                consecutive_failures: count,
            }
        }
    }
    return failing
}

function getMaxConsecutiveFailures(failing) {
    const counts = Object.values(failing).map((f) => f.consecutive_failures || 0)
    return counts.length > 0 ? Math.max(...counts) : 0
}

function getOldestFailingSince(failing) {
    const times = Object.values(failing).map((f) => new Date(f.since).getTime())
    return times.length > 0 ? Math.min(...times) : null
}

function determineAction(state, failing, threshold) {
    const failingNames = Object.keys(failing).sort()
    const failingList = failingNames.join(', ')
    const hasFailures = failingNames.length > 0
    const wasAlerted = state?.alerted === true

    if (!hasFailures && !wasAlerted) {
        return { action: 'none', failingList }
    }

    if (!hasFailures && wasAlerted) {
        return { action: 'resolve', failingList }
    }

    const maxConsecutive = getMaxConsecutiveFailures(failing)
    const thresholdReached = maxConsecutive >= threshold

    if (!thresholdReached && !wasAlerted) {
        return { action: 'none', failingList }
    }

    if (thresholdReached && !wasAlerted) {
        return { action: 'create', failingList }
    }

    // Already alerted — check if the failing set changed
    const previousList = state.last_failing_list || ''
    if (failingList !== previousList) {
        return { action: 'update', failingList }
    }

    return { action: 'none', failingList }
}

function buildFailingDetail(failing, criticalWorkflows) {
    const blocking = []
    const nonBlocking = []
    for (const [name, info] of Object.entries(failing)) {
        const link = `<${info.run_url}|${name}>`
        const entry = `${link} (${info.consecutive_failures} consecutive failures)`
        if (info.workflow_file && criticalWorkflows.has(info.workflow_file)) {
            blocking.push(entry)
        } else {
            nonBlocking.push(entry)
        }
    }
    let detail = ''
    if (blocking.length > 0) detail += `*Blocking:* ${blocking.join(', ')}`
    if (nonBlocking.length > 0) {
        if (detail) detail += '\n'
        detail += `*Non-blocking:* ${nonBlocking.join(', ')}`
    }
    return detail
}

module.exports = async ({ github, context, core }, { fs: _fs, now: _now } = {}) => {
    const fs = _fs || require('fs')
    const now = _now || new Date()

    const owner = context.repo.owner
    const repo = context.repo.repo

    const workflowFiles = (process.env.WATCHED_WORKFLOWS || '').split(',').filter(Boolean)
    const criticalWorkflows = new Set((process.env.CRITICAL_WORKFLOWS || '').split(',').filter(Boolean))
    const threshold = parseInt(process.env.ALERT_THRESHOLD_RUNS || '5', 10)
    const perPage = threshold * 2

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

    // Fetch recent runs for each watched workflow
    console.log(`Checking ${workflowFiles.length} workflows (last ${perPage} runs each)...`)
    const allWorkflowRuns = await Promise.all(
        workflowFiles.map((wf) =>
            fetchWorkflowRuns(github, owner, repo, wf, perPage).catch((err) => {
                console.log(`Failed to fetch ${wf}: ${err.message}`)
                return []
            })
        )
    )

    for (const runs of allWorkflowRuns) {
        if (runs.length > 0) {
            const count = countConsecutiveFailures(runs)
            console.log(
                `  ${runs[0].name}: ${runs[0].conclusion}${count > 0 ? ` (${count} consecutive failures)` : ''}`
            )
        }
    }

    // Build failing map from API data (recomputed each tick, no stale state)
    const failing = buildFailingMap(allWorkflowRuns)

    // Determine action
    const { action, failingList } = determineAction(state, failing, threshold)

    console.log(`Action: ${action}`)
    console.log(`Failing: ${failingList || 'none'}`)

    // Build failing detail for Slack messages
    const failingDetail = buildFailingDetail(failing, criticalWorkflows)

    // Save when there's an action or evolving failure counts to track
    const shouldSave = action !== 'none' || Object.keys(failing).length > 0
    const saveRateLimit = rateLimitAction !== 'none'

    // Build new state
    const newState = {
        failing,
        alerted: action === 'create' || (state?.alerted === true && action !== 'resolve'),
        slack_ts: state?.slack_ts || null,
        slack_channel: state?.slack_channel || null,
        last_failing_list: failingList,
        last_failing_detail: failingDetail || state?.last_failing_detail || '',
        resolved: action === 'resolve',
        rate_limit_alerted:
            rateLimitAction === 'create' || (state?.rate_limit_alerted === true && rateLimitAction !== 'resolve'),
        rate_limit_slack_ts: state?.rate_limit_slack_ts || null,
        rate_limit_slack_channel: state?.rate_limit_slack_channel || null,
    }

    if (shouldSave || saveRateLimit) {
        fs.writeFileSync(STATE_FILE, JSON.stringify(newState, null, 2))
    }

    // Set outputs
    core.setOutput('action', action)
    core.setOutput('save_cache', shouldSave || saveRateLimit ? 'true' : 'false')
    core.setOutput('delete_old_caches', action === 'create' ? 'true' : 'false')
    core.setOutput('failing_workflows', failingList)
    core.setOutput('failing_count', String(Object.keys(failing).length))

    if (action === 'create' || action === 'update') {
        const maxConsecutive = getMaxConsecutiveFailures(failing)
        const oldest = getOldestFailingSince(failing)
        const mins = oldest ? Math.round((now.getTime() - oldest) / 60000) : 0
        core.setOutput('max_consecutive', String(maxConsecutive))
        core.setOutput('duration_mins', String(mins))
        core.setOutput('failing_detail', failingDetail)
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

    if (action === 'resolve') {
        const previousFailing = state?.failing || {}
        const maxConsecutive = getMaxConsecutiveFailures(previousFailing)
        const oldest = getOldestFailingSince(previousFailing)
        const mins = oldest ? Math.round((now.getTime() - oldest) / 60000) : 0
        core.setOutput('max_consecutive', String(maxConsecutive))
        core.setOutput('duration_mins', String(mins))
        core.setOutput('slack_ts', state?.slack_ts || '')
        core.setOutput('slack_channel', state?.slack_channel || '')
        core.setOutput('last_failing_list', state?.last_failing_list || '')
        core.setOutput('last_failing_detail', state?.last_failing_detail || '')
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
