// Master CI Alerts — a single self-updating Slack incident for sustained master failures.
//
// Detection is stateless: every run recomputes master health from the GitHub API.
// Slack itself is the source of truth for incident continuity — each run reads back
// the bot's own anchor message (tagged via Slack message metadata) and reconciles.
// There is no external state store, so there are no cache races and the alerter
// self-heals: delete the anchor and the next run reposts; a missed run just
// reconciles on the next tick.
//
// Two signals make master "unhealthy" (folded into one incident):
//   1. any watched workflow with >= WORKFLOW_FAILURE_STREAK_THRESHOLD consecutive
//      failures on master — a single workflow broken run after run.
//   2. >= COMMIT_FAILURE_STREAK_THRESHOLD consecutive red commits across critical
//      workflows — rotating-culprit breakage where no single workflow crosses its
//      own threshold but master is still consistently red.
//
// Message model (chosen for UX: never lose history, never orphan a stuck message):
//   - Anchor: one top-level message, edited silently each tick to keep the live
//     summary current. On resolve its header is struck through and a green line
//     prepended — the close is visible, nothing is erased.
//   - Thread: append-only replies, one per *real change* (workflow crossed
//     threshold / recovered, commit-streak started, master green). An unchanged
//     tick refreshes the anchor duration only — no thread noise.
//
// GitHub API rate-limit observability is handled by the separate
// monitor-github-rate-limit workflow, which emits to PostHog as time series.

const SLACK_API = 'https://slack.com/api'
const INCIDENT_EVENT_TYPE = 'master_ci_incident'
const HISTORY_LIMIT = 100

// ---------------------------------------------------------------------------
// GitHub data
// ---------------------------------------------------------------------------

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

// Workflows whose newest run starts a failure streak, keyed by display name.
function buildFailingMap(allWorkflowRuns) {
    const failing = {}
    for (const runs of allWorkflowRuns) {
        if (runs.length === 0) continue
        const count = countConsecutiveFailures(runs)
        if (count > 0) {
            const latest = runs[0]
            const oldest = runs[count - 1]
            failing[latest.name] = {
                name: latest.name,
                since: oldest.updated_at,
                run_url: latest.run_url,
                workflow_file: latest.workflow_file,
                consecutive_failures: count,
            }
        }
    }
    return failing
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
        author: c.author?.login || c.commit?.author?.name || 'unknown',
        date: c.commit?.author?.date || null,
    }))
}

// Classify each commit by the critical-workflow runs that share its SHA.
// Non-critical workflows are intentionally ignored — per-workflow alerting
// already covers sticky non-critical breakage.
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
        if (runs.length === 0) return { ...commit, status: 'unknown' }
        const red = runs.some((r) => r.conclusion === 'failure' || r.conclusion === 'timed_out')
        return { ...commit, status: red ? 'red' : 'green' }
    })
}

// Walk newest-to-oldest, count reds, stop at the first green. Unknowns (CI still
// running, path-filtered) neither count nor break the streak, so a freshly-pushed
// commit whose CI hasn't completed does not mask a real underlying streak.
function countConsecutiveRedCommits(classified) {
    let count = 0
    for (const commit of classified) {
        if (commit.status === 'green') break
        if (commit.status === 'red') count++
    }
    return count
}

// Oldest commit timestamp within the leading red streak (for incident duration).
function oldestRedCommitDate(classified, count) {
    let seen = 0
    let date = null
    for (const commit of classified) {
        if (commit.status === 'green') break
        if (commit.status !== 'red') continue
        seen++
        if (commit.date) date = commit.date
        if (seen >= count) break
    }
    return date
}

// ---------------------------------------------------------------------------
// Slack client (injectable for tests)
// ---------------------------------------------------------------------------

function defaultSlackClient(token, fetchImpl) {
    const doFetch = fetchImpl || fetch
    const post = async (method, body) => {
        const res = await doFetch(`${SLACK_API}/${method}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json; charset=utf-8', Authorization: `Bearer ${token}` },
            body: JSON.stringify(body),
        })
        const data = await res.json()
        if (!data.ok) throw new Error(`slack ${method} failed: ${data.error}`)
        return data
    }
    return {
        postMessage: (args) => post('chat.postMessage', args),
        update: (args) => post('chat.update', args),
        // conversations.history is a read method — pass params in the query string.
        history: async ({ channel, limit }) => {
            const url = new URL(`${SLACK_API}/conversations.history`)
            url.searchParams.set('channel', channel)
            url.searchParams.set('limit', String(limit))
            url.searchParams.set('include_all_metadata', 'true')
            const res = await doFetch(url.toString(), { headers: { Authorization: `Bearer ${token}` } })
            const data = await res.json()
            if (!data.ok) throw new Error(`slack conversations.history failed: ${data.error}`)
            return data
        },
    }
}

// The bot's own open incident, identified purely by message metadata — no other
// app sets this event_type, so it is unambiguous without knowing our bot id.
async function findActiveIncident(slack, channel) {
    const { messages = [] } = await slack.history({ channel, limit: HISTORY_LIMIT })
    for (const message of messages) {
        const payload = message.metadata?.event_payload
        if (message.metadata?.event_type === INCIDENT_EVENT_TYPE && payload?.status === 'active') {
            return { ts: message.ts, payload }
        }
    }
    return null
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

function formatDuration(mins) {
    if (mins < 60) return `${mins}m`
    const h = Math.floor(mins / 60)
    const m = mins % 60
    return m === 0 ? `${h}h` : `${h}h ${m}m`
}

// Slack mrkdwn requires escaping these three in user-supplied text.
const slackEscape = (text) => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

// Critical workflows first, then by streak length descending.
function sortBlocking(blocking, criticalWorkflows) {
    return [...blocking].sort((a, b) => {
        const ac = criticalWorkflows.has(a.workflow_file) ? 0 : 1
        const bc = criticalWorkflows.has(b.workflow_file) ? 0 : 1
        return ac - bc || b.consecutive_failures - a.consecutive_failures
    })
}

function buildAnchorText({ blocking, commitActive, commitStreakCount, latestCommit, durationMins, runsUrl }) {
    const lines = [`:red_circle:  *Master is red* · ${formatDuration(durationMins)}`]
    for (const wf of blocking) {
        lines.push(
            `• <${wf.run_url}|${slackEscape(wf.name)}> — ${plural(wf.consecutive_failures, 'failed run')} in a row`
        )
    }
    if (commitActive) {
        lines.push(`_${plural(commitStreakCount, 'commit')} in a row failed a required check_`)
    }
    if (latestCommit) {
        const sha = latestCommit.sha.slice(0, 7)
        const msg = slackEscape((latestCommit.message || '').slice(0, 80))
        const tail = `Latest: <${latestCommit.html_url}|${sha}> ${msg} · ${slackEscape(latestCommit.author)} · <${runsUrl}|View failing runs>`
        lines.push(tail)
    } else {
        lines.push(`<${runsUrl}|View failing runs>`)
    }
    return lines.join('\n')
}

function buildResolvedText({ previousWorkflows, durationMins }) {
    const cleared = previousWorkflows.length ? previousWorkflows.join(', ') : 'required-check failures'
    return [
        `:large_green_circle:  *Master recovered* · was red ${formatDuration(durationMins)}`,
        `~*Master is red* — ${slackEscape(cleared)}~`,
    ].join('\n')
}

// One thread reply summarizing what changed this tick (or the initial state).
function buildThreadReply({ created, added, removed, commitStarted, resolved, durationMins }) {
    if (resolved) return `:white_check_mark: master green again — was red ${formatDuration(durationMins)}`
    const parts = []
    if (created.length) {
        parts.push(...created.map((w) => `:red_circle: ${slackEscape(w)} crossed the failure threshold`))
    }
    if (added.length) parts.push(`:heavy_plus_sign: now also failing: ${slackEscape(added.join(', '))}`)
    if (removed.length) parts.push(`:white_check_mark: recovered: ${slackEscape(removed.join(', '))}`)
    if (commitStarted) parts.push(`:red_circle: commit-failure streak crossed the threshold`)
    return parts.join('\n')
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

module.exports = async ({ context, github, core }, { now: _now, slack: _slack, fetch: _fetch } = {}) => {
    const now = _now || new Date()
    const owner = context.repo.owner
    const repo = context.repo.repo
    const channel = process.env.SLACK_CHANNEL
    const slack = _slack || defaultSlackClient(process.env.SLACK_BOT_TOKEN, _fetch)

    const workflowFiles = (process.env.WATCHED_WORKFLOWS || '').split(',').filter(Boolean)
    const criticalWorkflows = new Set((process.env.CRITICAL_WORKFLOWS || '').split(',').filter(Boolean))
    const workflowThreshold = parseInt(process.env.WORKFLOW_FAILURE_STREAK_THRESHOLD || '5', 10)
    const commitThreshold = parseInt(process.env.COMMIT_FAILURE_STREAK_THRESHOLD || '10', 10)
    // Over-fetch to survive cancelled/skipped runs (force-pushes, concurrency cancels).
    const perPage = Math.max(workflowThreshold * 3, 20)
    const commitsToFetch = Math.max(commitThreshold * 2, 25)

    // 1. Recompute master health from the API (no stored state).
    const allWorkflowRuns = await Promise.all(
        workflowFiles.map((wf) =>
            fetchWorkflowRuns(github, owner, repo, wf, perPage).catch((err) => {
                core.warning(`Failed to fetch ${wf}: ${err.message}`)
                return []
            })
        )
    )
    const failing = buildFailingMap(allWorkflowRuns)
    const blocking = sortBlocking(
        Object.values(failing).filter((f) => f.consecutive_failures >= workflowThreshold),
        criticalWorkflows
    )

    let commitStreakCount = 0
    let commitStreakSince = null
    let latestCommit = null
    try {
        const commits = await fetchRecentCommits(github, owner, repo, commitsToFetch)
        latestCommit = commits[0] || null
        const classified = classifyCommits(commits, allWorkflowRuns, criticalWorkflows)
        commitStreakCount = countConsecutiveRedCommits(classified)
        commitStreakSince = oldestRedCommitDate(classified, commitStreakCount)
    } catch (err) {
        core.warning(`Failed to compute red commits: ${err.message}`)
    }
    const commitActive = commitStreakCount >= commitThreshold
    const unhealthy = blocking.length > 0 || commitActive

    // 2. Slack is the source of truth for whether an incident is already open.
    const active = await findActiveIncident(slack, channel)
    const runsUrl = `https://github.com/${owner}/${repo}/actions?query=branch%3Amaster+is%3Afailure`

    // Earliest start across both active signals (preserve original on update).
    const computeSince = () => {
        const times = blocking.map((b) => new Date(b.since).getTime())
        if (commitActive && commitStreakSince) times.push(new Date(commitStreakSince).getTime())
        return times.length ? new Date(Math.min(...times)).toISOString() : now.toISOString()
    }

    let action = 'none'

    if (unhealthy) {
        const blockingNames = blocking.map((b) => b.name)
        const since = active?.payload?.since || computeSince()
        const durationMins = Math.round((now.getTime() - new Date(since).getTime()) / 60000)
        const text = buildAnchorText({ blocking, commitActive, commitStreakCount, latestCommit, durationMins, runsUrl })
        const metadata = {
            event_type: INCIDENT_EVENT_TYPE,
            event_payload: { status: 'active', since, workflows: blockingNames, commitActive },
        }

        if (!active) {
            const posted = await slack.postMessage({ channel, text, metadata, unfurl_links: false })
            await slack.postMessage({
                channel,
                thread_ts: posted.ts,
                text: buildThreadReply({ created: blockingNames, added: [], removed: [], commitStarted: commitActive }),
            })
            action = 'create'
        } else {
            await slack.update({ channel, ts: active.ts, text, metadata })
            // Diff against the previous set to decide whether the timeline moved.
            const prev = new Set(active.payload?.workflows || [])
            const curr = new Set(blockingNames)
            const added = [...curr].filter((n) => !prev.has(n))
            const removed = [...prev].filter((n) => !curr.has(n))
            const commitStarted = commitActive && !active.payload?.commitActive
            if (added.length || removed.length || commitStarted) {
                await slack.postMessage({
                    channel,
                    thread_ts: active.ts,
                    text: buildThreadReply({ created: [], added, removed, commitStarted }),
                })
            }
            action = 'update'
        }
    } else if (active) {
        const since = active.payload?.since
        const durationMins = since ? Math.round((now.getTime() - new Date(since).getTime()) / 60000) : 0
        const previousWorkflows = active.payload?.workflows || []
        await slack.update({
            channel,
            ts: active.ts,
            text: buildResolvedText({ previousWorkflows, durationMins }),
            metadata: { event_type: INCIDENT_EVENT_TYPE, event_payload: { status: 'resolved' } },
        })
        await slack.postMessage({
            channel,
            thread_ts: active.ts,
            text: buildThreadReply({ created: [], added: [], removed: [], resolved: true, durationMins }),
        })
        action = 'resolve'
    }

    core.info(
        `Action: ${action} | blocking: ${blocking.map((b) => b.name).join(', ') || 'none'} | commit streak: ${commitStreakCount}`
    )
    core.setOutput('action', action)
    core.setOutput('blocking_count', String(blocking.length))
    core.setOutput('commit_streak', String(commitStreakCount))
}

module.exports.buildFailingMap = buildFailingMap
module.exports.countConsecutiveFailures = countConsecutiveFailures
module.exports.countConsecutiveRedCommits = countConsecutiveRedCommits
module.exports.classifyCommits = classifyCommits
module.exports.buildAnchorText = buildAnchorText
module.exports.buildResolvedText = buildResolvedText
module.exports.formatDuration = formatDuration
module.exports.findActiveIncident = findActiveIncident
