// Master CI Alerts - Cron-based rolling window alert for sustained master failures
//
// Polls the GitHub API every 10 minutes. Emits two independent signals:
//
// 1. Per-workflow streak: alerts when any watched workflow has
//    WORKFLOW_FAILURE_STREAK_THRESHOLD (default 5) consecutive failures on master.
//    Catches a single workflow broken run after run.
//
// 2. Commit-level health: alerts when COMMIT_FAILURE_STREAK_THRESHOLD (default 10)
//    consecutive commits on master each had at least one critical workflow
//    fail. Catches rotating-culprit breakage (3 dagster flakes, 3 storybook
//    flakes, etc.) where no single workflow hits the per-workflow threshold
//    but master is still consistently red.
//
// GitHub API rate-limit observability is handled by the separate
// monitor-github-rate-limit workflow, which emits to PostHog as time series.
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
//   commit_failure_streak_alerted: boolean,
//   commit_failure_streak_slack_ts: string | null,
//   commit_failure_streak_slack_channel: string | null,
//   commit_failure_streak_last_count: number,
//   commit_failure_streak_last_sample: string,  // preserved for resolve messages
// }

const STATE_FILE = '.alerts-devex'

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

// Decision matrix (hasFailures × wasAlerted × thresholdReached):
//   no failures, not alerted          → none
//   no failures, alerted              → resolve
//   failures, not alerted, under      → none
//   failures, not alerted, at/over    → create
//   failures, alerted, set changed    → update
//   failures, alerted, set unchanged  → none
function determineAction(state, failing, workflowFailureStreakThreshold) {
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
    const thresholdReached = maxConsecutive >= workflowFailureStreakThreshold

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

async function fetchRecentCommits(github, owner, repo, perPage) {
    const { data } = await github.rest.repos.listCommits({
        owner,
        repo,
        sha: 'master',
        per_page: perPage,
    })
    return data.map((c) => ({
        sha: c.sha,
        html_url: c.html_url,
        message: (c.commit?.message || '').split('\n')[0],
        author: c.commit?.author?.name || 'unknown',
    }))
}

// Classify each commit by looking up critical-workflow runs that share its SHA.
// Non-critical workflow runs are intentionally ignored — they're the noisy ones,
// and per-workflow alerting already covers sticky non-critical breakage.
function classifyCommits(commits, allWorkflowRuns, criticalWorkflows) {
    const runsBySha = new Map()
    for (const runs of allWorkflowRuns) {
        for (const run of runs) {
            if (!criticalWorkflows.has(run.workflow_file)) continue
            if (!runsBySha.has(run.sha)) runsBySha.set(run.sha, [])
            runsBySha.get(run.sha).push(run)
        }
    }
    return commits.map((commit) => {
        const runs = runsBySha.get(commit.sha) || []
        if (runs.length === 0) {
            return { ...commit, status: 'unknown', redWorkflows: [] }
        }
        const red = runs.filter((r) => r.conclusion === 'failure' || r.conclusion === 'timed_out')
        if (red.length > 0) {
            return { ...commit, status: 'red', redWorkflows: red.map((r) => r.name) }
        }
        return { ...commit, status: 'green', redWorkflows: [] }
    })
}

// Walk newest-to-oldest, count reds, stop at the first green.
// Unknowns (workflows still running, path-filtered, etc.) are skipped: they
// neither count nor break the streak. Rationale: a freshly-pushed commit
// whose CI hasn't completed yet should not mask a real underlying streak.
function countConsecutiveRedCommits(classified) {
    let count = 0
    for (const commit of classified) {
        if (commit.status === 'green') break
        if (commit.status === 'red') count++
    }
    return count
}

function determineCommitFailureStreakAction(state, count, threshold) {
    const wasAlerted = state?.commit_failure_streak_alerted === true
    const atOrOver = count >= threshold

    if (!atOrOver && !wasAlerted) return 'none'
    if (!atOrOver && wasAlerted) return 'resolve'
    if (atOrOver && !wasAlerted) return 'create'
    // Already alerted AND still at/over threshold — update only when count grew
    const prev = state?.commit_failure_streak_last_count || 0
    if (count > prev) return 'update'
    return 'none'
}

function buildCommitFailureStreakDetail(classified, count) {
    if (count === 0) return ''
    const redOnly = classified.filter((c) => c.status === 'red').slice(0, count)
    const lines = redOnly.map((c) => {
        const shortSha = c.sha.slice(0, 7)
        const workflows = c.redWorkflows.join(', ')
        return `• <${c.html_url}|${shortSha}> — ${workflows}`
    })
    return lines.join('\n')
}

module.exports = async ({ github, context, core }, { fs: _fs, now: _now } = {}) => {
    const fs = _fs || require('fs')
    const now = _now || new Date()

    const owner = context.repo.owner
    const repo = context.repo.repo

    const workflowFiles = (process.env.WATCHED_WORKFLOWS || '').split(',').filter(Boolean)
    const criticalWorkflows = new Set((process.env.CRITICAL_WORKFLOWS || '').split(',').filter(Boolean))
    const workflowFailureStreakThreshold = parseInt(process.env.WORKFLOW_FAILURE_STREAK_THRESHOLD || '5', 10)
    const commitFailureStreakThreshold = parseInt(process.env.COMMIT_FAILURE_STREAK_THRESHOLD || '10', 10)
    // Over-fetch to survive cancelled/skipped runs (force-pushes, concurrency cancels).
    // If the filtered set ends up smaller than workflowFailureStreakThreshold, we log a warning.
    const perPage = Math.max(workflowFailureStreakThreshold * 3, 20)
    const commitsToFetch = Math.max(commitFailureStreakThreshold * 2, 25)

    // Load existing state
    let state = null
    if (fs.existsSync(STATE_FILE)) {
        try {
            const raw = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'))
            if (raw.resolved) {
                console.log('Found resolved incident, treating as no active state')
                state = {
                    failing: {},
                    commit_failure_streak_alerted: raw.commit_failure_streak_alerted ?? false,
                    commit_failure_streak_slack_ts: raw.commit_failure_streak_slack_ts ?? null,
                    commit_failure_streak_slack_channel: raw.commit_failure_streak_slack_channel ?? null,
                    commit_failure_streak_last_count: raw.commit_failure_streak_last_count ?? 0,
                    commit_failure_streak_last_sample: raw.commit_failure_streak_last_sample ?? '',
                }
            } else {
                state = { failing: {}, ...raw }
                console.log('Loaded existing state')
            }
        } catch (e) {
            console.log('Failed to parse state file, treating as fresh')
        }
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
            if (runs.length < workflowFailureStreakThreshold) {
                console.log(
                    `  ! Only ${runs.length} non-cancelled runs available for ${runs[0].name} — below threshold of ${workflowFailureStreakThreshold}`
                )
            }
        }
    }

    // Build failing map from API data (recomputed each tick, no stale state)
    const failing = buildFailingMap(allWorkflowRuns)

    // Determine action
    const { action, failingList } = determineAction(state, failing, workflowFailureStreakThreshold)

    console.log(`Action: ${action}`)
    console.log(`Failing: ${failingList || 'none'}`)

    // Build failing detail for Slack messages
    const failingDetail = buildFailingDetail(failing, criticalWorkflows)

    // Commit-level health: independent signal tracking consecutive red commits
    // across critical workflows. Fetches real commit order via listCommits so
    // force-pushes don't confuse the streak.
    let classified = []
    let commitFailureStreakCount = 0
    let commitFailureStreakAction = 'none'
    try {
        const commits = await fetchRecentCommits(github, owner, repo, commitsToFetch)
        classified = classifyCommits(commits, allWorkflowRuns, criticalWorkflows)
        commitFailureStreakCount = countConsecutiveRedCommits(classified)
        commitFailureStreakAction = determineCommitFailureStreakAction(state, commitFailureStreakCount, commitFailureStreakThreshold)
        console.log(`Red commits streak: ${commitFailureStreakCount} (action: ${commitFailureStreakAction})`)
    } catch (err) {
        console.log(`Failed to compute red commits: ${err.message}`)
    }
    const commitFailureStreakDetail = buildCommitFailureStreakDetail(classified, commitFailureStreakCount)

    // Save when there's an action or evolving failure counts to track
    const shouldSave = action !== 'none' || Object.keys(failing).length > 0
    const saveCommitFailureStreak = commitFailureStreakAction !== 'none' || commitFailureStreakCount > 0

    // Build new state
    const newState = {
        failing,
        alerted: action === 'create' || (state?.alerted === true && action !== 'resolve'),
        slack_ts: state?.slack_ts || null,
        slack_channel: state?.slack_channel || null,
        last_failing_list: failingList,
        last_failing_detail: failingDetail || state?.last_failing_detail || '',
        resolved: action === 'resolve',
        commit_failure_streak_alerted:
            commitFailureStreakAction === 'create' ||
            (state?.commit_failure_streak_alerted === true && commitFailureStreakAction !== 'resolve'),
        commit_failure_streak_slack_ts: state?.commit_failure_streak_slack_ts || null,
        commit_failure_streak_slack_channel: state?.commit_failure_streak_slack_channel || null,
        commit_failure_streak_last_count: commitFailureStreakAction === 'resolve' ? 0 : commitFailureStreakCount,
        commit_failure_streak_last_sample: commitFailureStreakDetail || state?.commit_failure_streak_last_sample || '',
    }

    if (shouldSave || saveCommitFailureStreak) {
        fs.writeFileSync(STATE_FILE, JSON.stringify(newState, null, 2))
    }

    // Set outputs
    core.setOutput('action', action)
    core.setOutput('save_cache', shouldSave || saveCommitFailureStreak ? 'true' : 'false')
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

    // Commit-failure-streak outputs
    core.setOutput('commit_failure_streak_action', commitFailureStreakAction)
    core.setOutput('commit_failure_streak_count', String(commitFailureStreakCount))
    if (commitFailureStreakAction === 'create' || commitFailureStreakAction === 'update') {
        core.setOutput('commit_failure_streak_detail', commitFailureStreakDetail)
    }
    if (commitFailureStreakAction === 'update' || commitFailureStreakAction === 'resolve') {
        core.setOutput('commit_failure_streak_slack_ts', state?.commit_failure_streak_slack_ts || '')
        core.setOutput('commit_failure_streak_slack_channel', state?.commit_failure_streak_slack_channel || '')
    }
    if (commitFailureStreakAction === 'resolve') {
        core.setOutput('commit_failure_streak_last_count', String(state?.commit_failure_streak_last_count || 0))
        core.setOutput('commit_failure_streak_last_sample', state?.commit_failure_streak_last_sample || '')
    }
}
