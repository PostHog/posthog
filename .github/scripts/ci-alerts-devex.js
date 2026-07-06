// Master CI Alerts — a single self-updating Slack incident for sustained master failures.
//
// Detection is stateless: every run recomputes master health from the GitHub API.
// Slack itself is the source of truth for incident continuity — each run reads back
// the bot's own anchor message (tagged via Slack message metadata) and reconciles.
// There is no external state store, so there are no cache races and the alerter
// self-heals: delete the anchor and the next run reposts; a missed run just
// reconciles on the next tick. (A duration-only incident deleted during a quiet period
// reposts only once pushes resume.)
//
// Two signals make master "unhealthy" (folded into one incident):
//   1. any gating workflow failing run-after-run (>= WORKFLOW_FAILURE_STREAK_THRESHOLD
//      consecutive failures) OR red for >= WORKFLOW_FAILURE_MINUTES_THRESHOLD minutes. The
//      wall-clock arm only OPENS an incident while master is still being pushed (a commit
//      within ACTIVITY_WINDOW_MINUTES), so a master sitting red over a quiet weekend doesn't
//      page; an open incident still resolves only on green.
//   2. >= COMMIT_FAILURE_STREAK_THRESHOLD consecutive red commits across the gating
//      workflows — rotating-culprit breakage where no single workflow crosses its
//      own threshold but master is still consistently red.
//
// Message model (chosen for UX: never lose history, never orphan a stuck message):
//   - Anchor: one top-level message, edited silently each tick to keep the live
//     summary current. On resolve its header is struck through and a green line
//     prepended — the close is visible, nothing is erased.
//   - Thread: append-only replies, one per *real change* (workflow started failing
//     / recovered, commit-streak started, master green). An unchanged
//     tick refreshes the anchor duration only — no thread noise.
//
// GitHub API rate-limit observability is handled by the separate
// monitor-github-rate-limit workflow, which emits to PostHog as time series.

const SLACK_API = 'https://slack.com/api'
const INCIDENT_EVENT_TYPE = 'master_ci_incident'
// One page of channel history. #alerts-devex is low-traffic, so the open anchor
// reliably stays within the newest 100 messages; a busier channel would need paging.
const HISTORY_LIMIT = 100
// Attachment side-bar colors (Slack's red / green).
const ACTIVE_COLOR = '#E01E5A'
const RESOLVED_COLOR = '#2EB67D'
// Caps the *displayed* red duration only (not detection): the shown span won't bridge a gap this
// wide between kept failures, so it can't anchor to a stale run.
const STREAK_MAX_GAP_MINUTES = 180
// Freshness bound for the runs-list index (see fetchWorkflowRuns): every gating workflow runs on
// every master push, so a fresh page's newest run trails the newest master commit by minutes.
// Generous enough to absorb supersede-cancelled bursts and webhook lag; stale pages trail by days.
const RUN_INDEX_MAX_LAG_MINUTES = 180
// Staleness is per-request (a fresh read seconds later succeeds), so retry before giving up.
const STALE_PAGE_RETRIES = 2
const STALE_PAGE_RETRY_DELAY_MS = 15000

const defaultSleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// ---------------------------------------------------------------------------
// GitHub data
// ---------------------------------------------------------------------------

// The single definition of a "red" run conclusion, shared by the streak and commit checks.
const isFailure = (run) => run.conclusion === 'failure' || run.conclusion === 'timed_out'

// The freshest settled runs for a workflow, newest-first.
//
// The runs-list API is served from an eventually-consistent index that intermittently returns a
// page anchored hours/days in the past — the alerter then reads an ancient failure as the newest
// run and backdates a phantom multi-day outage (opened+resolved in seconds, "red for 141h").
// Dropping `status: 'completed'` was not enough: the branch/event filters hit the same index, and
// the same stale page came back. So freshness is now *verified*, not assumed: every gating workflow
// runs on every master push, so a fresh page's newest raw run tracks the newest master commit
// within minutes. A page whose newest run trails `freshAsOf` (the newest commit's push time, from
// the strongly-consistent Git backend) by more than RUN_INDEX_MAX_LAG_MINUTES is stale — retry,
// then throw so the caller treats this workflow as unreadable this tick, never as green.
//
// The catch: `per_page` truncates the raw page BEFORE our client-side filter, so a head full of
// in-progress/cancelled runs could push real completed failures off a single page and silently miss
// an incident. So we page until the leading streak is settled (a kept non-failure bounds the walk)
// or we hit a bounded cap.
async function fetchWorkflowRuns(github, owner, repo, workflowFile, perPage, { freshAsOf = null, sleep = defaultSleep } = {}) {
    for (let attempt = 0; ; attempt++) {
        try {
            return await fetchSettledRuns(github, owner, repo, workflowFile, perPage, freshAsOf)
        } catch (err) {
            if (!err.staleIndex || attempt >= STALE_PAGE_RETRIES) throw err
            await sleep(STALE_PAGE_RETRY_DELAY_MS)
        }
    }
}

async function fetchSettledRuns(github, owner, repo, workflowFile, perPage, freshAsOf) {
    const MAX_PAGES = 5
    const settled = []
    for (let page = 1; page <= MAX_PAGES; page++) {
        const { data } = await github.rest.actions.listWorkflowRuns({
            owner,
            repo,
            workflow_id: workflowFile,
            branch: 'master',
            event: 'push',
            per_page: perPage,
            page,
        })
        // Judge index freshness on the raw page-1 head (any status) before paging deeper. An empty
        // page while master has commits is the same anomaly as a lagging one — every gating
        // workflow has master-push history, so its absence is unreadable, not "no failures".
        if (page === 1 && freshAsOf) {
            const head = data.workflow_runs[0]
            // Empty page → Infinity (stale); NaN (unparseable dates) falls through to fresh.
            const lagMins = head
                ? (new Date(freshAsOf).getTime() - new Date(head.created_at).getTime()) / 60000
                : Infinity
            if (lagMins > RUN_INDEX_MAX_LAG_MINUTES) {
                const err = new Error(
                    `stale runs index: newest run ${head?.created_at || 'absent'} trails newest master commit ${freshAsOf}`
                )
                err.staleIndex = true
                throw err
            }
        }
        for (const run of data.workflow_runs) {
            // In-progress/queued must neither count as nor break a failure streak (mirroring how
            // unreported commits classify 'unknown'); cancelled/skipped never reflect real health.
            if (run.status !== 'completed') continue
            if (run.conclusion === 'cancelled' || run.conclusion === 'skipped') continue
            settled.push({
                name: run.name,
                conclusion: run.conclusion,
                sha: run.head_sha,
                run_url: run.html_url,
                updated_at: run.updated_at,
                created_at: run.created_at, // immutable; updated_at is bumped by re-runs
                workflow_file: workflowFile,
            })
        }
        // Once a kept run is a non-failure it terminates the leading streak, so we have all we need.
        // A short raw page means there are no older runs to fetch.
        const streakBounded = settled.some((r) => !isFailure(r))
        if (streakBounded || data.workflow_runs.length < perPage) break
    }
    return settled
}

function countConsecutiveFailures(runs) {
    let count = 0
    for (const run of runs) {
        if (isFailure(run)) {
            count++
        } else {
            break
        }
    }
    return count
}

// Display-only "red since": oldest failure reachable from the newest without crossing a gap wider
// than STREAK_MAX_GAP_MINUTES. Uses immutable created_at so re-runs can't collapse the span.
function contiguousFailureSince(runs, count) {
    const dispatchedAt = (run) => run.created_at || run.updated_at
    let oldest = runs[0]
    for (let i = 1; i < count; i++) {
        const gapMins = (new Date(dispatchedAt(runs[i - 1])).getTime() - new Date(dispatchedAt(runs[i])).getTime()) / 60000
        if (!(gapMins <= STREAK_MAX_GAP_MINUTES)) break // NaN-safe
        oldest = runs[i]
    }
    return dispatchedAt(oldest)
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
                since: oldest.updated_at, // detection (full streak)
                displaySince: contiguousFailureSince(runs, count), // display only (gap-bounded)
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
        // Committer date = push/merge time. The author date on a squash merge is the branch's
        // first commit — days old, which would suppress the activity gate and backdate durations.
        date: c.commit?.committer?.date || c.commit?.author?.date || null,
    }))
}

// Classify each commit by the gating workflow runs that share its SHA: red if any
// failed, green if all reported and passed, unknown if none have reported yet
// (CI still running / path-filtered).
function classifyCommits(commits, allWorkflowRuns) {
    const runsBySha = new Map()
    for (const runs of allWorkflowRuns) {
        for (const run of runs) {
            if (!runsBySha.has(run.sha)) runsBySha.set(run.sha, [])
            runsBySha.get(run.sha).push(run)
        }
    }
    return commits.map((commit) => {
        const runs = runsBySha.get(commit.sha) || []
        if (runs.length === 0) return { ...commit, status: 'unknown' }
        const red = runs.some(isFailure)
        return { ...commit, status: red ? 'red' : 'green' }
    })
}

// Walk newest-to-oldest over the leading red streak, returning its length and the
// oldest red commit's timestamp (for incident duration). Stop at the first green;
// unknowns (CI still running, path-filtered) neither count nor break the streak, so
// a freshly-pushed commit whose CI hasn't completed does not mask a real streak.
function leadingRedStreak(classified) {
    let count = 0
    let since = null
    for (const commit of classified) {
        if (commit.status === 'green') break
        if (commit.status !== 'red') continue
        count++
        if (commit.date) since = commit.date
    }
    return { count, since }
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

// A workflow's run history on master — where you can see all of its runs at a glance.
function runsUrlFor(owner, repo, workflowFile) {
    return `https://github.com/${owner}/${repo}/actions/workflows/${workflowFile}?query=branch%3Amaster`
}

// Read-boundary normalizer for persisted incident workflows: tolerate an older
// bare-name format so a metadata schema change can't break the resolve/diff path.
const normalizeWorkflows = (list) => (list || []).map((w) => (typeof w === 'string' ? { name: w } : w))

// Bold, linked workflow name → its master run history.
const workflowLink = (wf) => `*<${wf.runsUrl}|${slackEscape(wf.name)}>*`

// The anchor: a red-barred Block Kit message. `text` is the notification/a11y fallback;
// the rich content lives in one attachment so it gets the colored side bar.
function buildAnchorMessage({
    blocking,
    commitActive,
    commitStreakCount,
    latestCommit,
    durationMins,
    allFailingRunsUrl,
}) {
    // Duration-only blockers show just the red time — no sub-threshold "N failed runs" count.
    const lines = blocking.map((wf) =>
        wf.byCount
            ? `• ${workflowLink(wf)} — ${plural(wf.consecutive_failures, 'failed run')} in a row · red for ${formatDuration(wf.displayRedForMins)}`
            : `• ${workflowLink(wf)} — red for ${formatDuration(wf.displayRedForMins)}`
    )
    if (commitActive) {
        lines.push(`• _${plural(commitStreakCount, 'commit')} in a row failed a required check_`)
    }

    const meta = [`failing for *${formatDuration(durationMins)}*`]
    if (latestCommit) {
        const sha = latestCommit.sha.slice(0, 7)
        const msg = slackEscape((latestCommit.message || '').slice(0, 80))
        meta.push(`latest <${latestCommit.html_url}|\`${sha}\`> ${msg} · *${slackEscape(latestCommit.author)}*`)
    }
    meta.push(`<${allFailingRunsUrl}|all failing runs ↗>`)

    const blocks = [
        { type: 'header', text: { type: 'plain_text', text: ':red_circle: Master is red', emoji: true } },
        { type: 'section', text: { type: 'mrkdwn', text: lines.join('\n') } },
        { type: 'context', elements: [{ type: 'mrkdwn', text: meta.join('  ·  ') }] },
    ]
    const summary = blocking.length
        ? `Master is red — ${plural(blocking.length, 'workflow')} failing (${formatDuration(durationMins)})`
        : `Master is red — ${plural(commitStreakCount, 'commit')} in a row failed a required check (${formatDuration(durationMins)})`
    return { text: summary, attachments: [{ color: ACTIVE_COLOR, blocks }] }
}

// The resolved anchor: green bar, recovery header, and the cleared workflows struck through.
function buildResolvedMessage({ previousWorkflows, durationMins }) {
    const cleared = previousWorkflows.length
        ? previousWorkflows.map((w) => slackEscape(w.name)).join(', ')
        : 'required-check failures'
    const blocks = [
        { type: 'header', text: { type: 'plain_text', text: ':large_green_circle: Master recovered', emoji: true } },
        {
            type: 'context',
            elements: [
                { type: 'mrkdwn', text: `was red for *${formatDuration(durationMins)}* · cleared: ~${cleared}~` },
            ],
        },
    ]
    return {
        text: `Master recovered — was red ${formatDuration(durationMins)}`,
        attachments: [{ color: RESOLVED_COLOR, blocks }],
    }
}

// One thread reply summarizing what changed this tick — the initial failing set on
// create, or the delta on later ticks. Workflow names link to their run history.
function buildThreadReply({ created = [], added = [], removed = [], commitStarted = false }) {
    const parts = []
    if (created.length) {
        // Arm-neutral wording: the anchor bullet already says count vs. duration.
        parts.push(...created.map((wf) => `:red_circle: ${workflowLink(wf)} is now failing master`))
    }
    if (added.length) parts.push(`:heavy_plus_sign: now also failing: ${added.map(workflowLink).join(', ')}`)
    if (removed.length) parts.push(`:white_check_mark: recovered: ${removed.map(workflowLink).join(', ')}`)
    if (commitStarted) parts.push(`:red_circle: commit-failure streak crossed the threshold`)
    return parts.join('\n')
}

function buildRecoveryReply(durationMins) {
    return `:white_check_mark: master green again — was red ${formatDuration(durationMins)}`
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

module.exports = async ({ context, github, core }, { now: _now, slack: _slack, fetch: _fetch, sleep: _sleep } = {}) => {
    const now = _now || new Date()
    const sleep = _sleep || defaultSleep
    const owner = context.repo.owner
    const repo = context.repo.repo
    const channel = process.env.SLACK_CHANNEL
    const slack = _slack || defaultSlackClient(process.env.SLACK_BOT_TOKEN, _fetch)

    const workflowFiles = (process.env.GATING_WORKFLOWS || '').split(',').filter(Boolean)
    const workflowThreshold = parseInt(process.env.WORKFLOW_FAILURE_STREAK_THRESHOLD || '5', 10)
    const minutesThreshold = parseInt(process.env.WORKFLOW_FAILURE_MINUTES_THRESHOLD || '20', 10)
    const activityWindowMins = parseInt(process.env.ACTIVITY_WINDOW_MINUTES || '120', 10)
    const commitThreshold = parseInt(process.env.COMMIT_FAILURE_STREAK_THRESHOLD || '10', 10)
    // Page size for the run fetch. fetchWorkflowRuns pages until the streak is settled, so this only
    // trades round-trips against page size; keep it wide enough to resolve the common case in one page
    // despite the in-progress/cancelled runs it now drops client-side. Clamp to GitHub's per_page max
    // of 100 (silently capped otherwise) so a tuned-up streak threshold can't quietly lose capacity.
    const perPage = Math.min(Math.max(workflowThreshold * 6, 40), 100)
    const commitsToFetch = Math.max(commitThreshold * 2, 25)

    // The Slack incident read (the source of truth for whether an incident is open) depends on
    // nothing — start it first so it overlaps the GitHub reads.
    const activePromise = findActiveIncident(slack, channel)

    // Commits come from the strongly-consistent Git backend, so they anchor the runs-index
    // freshness check — fetch them before any runs read. null (not []) on failure: without the
    // anchor no runs page is verifiable, so every workflow is unreadable this tick rather than
    // trusted unverified (a stale page could otherwise open a phantom via the streak-count arm).
    const commits = await fetchRecentCommits(github, owner, repo, commitsToFetch).catch((err) => {
        core.warning(`Failed to fetch commits: ${err.message}`)
        return null
    })
    const freshAsOf = commits?.[0]?.date || null

    // A workflow whose runs can't be read (API error or a persistently stale page) is null:
    // unreadable, distinct from "no failures".
    const [fetchedRuns, active] = await Promise.all([
        commits === null
            ? workflowFiles.map(() => null)
            : Promise.all(
                  workflowFiles.map((wf) =>
                      fetchWorkflowRuns(github, owner, repo, wf, perPage, { freshAsOf, sleep }).catch((err) => {
                          core.warning(`No usable runs for ${wf}: ${err.message}`)
                          return null
                      })
                  )
              ),
        activePromise,
    ])
    const knownRuns = fetchedRuns.filter((runs) => runs !== null)
    // Complete = every read succeeded and passed the freshness check. Reconciling an open
    // incident on less would let a stale page or failed fetch masquerade as recovery.
    const dataComplete = commits !== null && knownRuns.length === fetchedRuns.length

    const failing = buildFailingMap(knownRuns)
    // byDuration catches slow-velocity breakage that never stacks up a full failure streak.
    const blocking = Object.values(failing)
        .map((f) => {
            const redForMins = Math.round((now.getTime() - new Date(f.since).getTime()) / 60000)
            return {
                ...f,
                runsUrl: runsUrlFor(owner, repo, f.workflow_file),
                redForMins, // detection: byDuration + open/resolve thresholds
                displayRedForMins: Math.round((now.getTime() - new Date(f.displaySince).getTime()) / 60000),
                byCount: f.consecutive_failures >= workflowThreshold,
                byDuration: redForMins >= minutesThreshold,
            }
        })
        .filter((f) => f.byCount || f.byDuration)
        .sort((a, b) => b.redForMins - a.redForMins) // most-severe (longest true red) first

    const latestCommit = commits?.[0] || null
    // Fail closed: no dated commit → not recent → the wall-clock arm won't open.
    const recentActivity =
        latestCommit?.date != null && now.getTime() - new Date(latestCommit.date).getTime() <= activityWindowMins * 60000

    const { count: commitStreakCount, since: commitStreakSince } = leadingRedStreak(
        classifyCommits(commits || [], knownRuns)
    )
    const commitActive = commitStreakCount >= commitThreshold
    // Sustains/resolves an open incident — ungated, so a stale-red master stays unhealthy
    // and an open incident resolves only on genuine green.
    const unhealthy = blocking.length > 0 || commitActive
    // Gates OPENING a new incident on recent push activity — the weekend-safety gate.
    const shouldOpen = commitActive || blocking.some((f) => f.byCount || (f.byDuration && recentActivity))

    const allFailingRunsUrl = `https://github.com/${owner}/${repo}/actions?query=branch%3Amaster+is%3Afailure`

    // Earliest start across both active signals (preserve original on update); gap-bounded displaySince.
    const computeSince = () => {
        const times = blocking.map((b) => new Date(b.displaySince).getTime())
        if (commitActive && commitStreakSince) times.push(new Date(commitStreakSince).getTime())
        return times.length ? new Date(Math.min(...times)).toISOString() : now.toISOString()
    }

    let action = 'none'

    // Open incident: sustain while unhealthy, else resolve. No incident: open only if shouldOpen.
    const shouldWriteAnchor = active ? unhealthy : shouldOpen

    if (active && !dataComplete) {
        // Hold: with any workflow unreadable this tick we can't tell recovery from a stale read,
        // and an anchor update would misreport the failing set. The next tick reconciles.
        core.warning('Incomplete CI data with an open incident — holding, no reconcile this tick')
        action = 'hold'
    } else if (shouldWriteAnchor) {
        // Carry name + runs link in metadata so later ticks can diff and re-link by name.
        const workflows = blocking.map((b) => ({ name: b.name, runsUrl: b.runsUrl }))
        const since = active?.payload?.since || computeSince()
        const durationMins = Math.round((now.getTime() - new Date(since).getTime()) / 60000)
        const message = buildAnchorMessage({
            blocking,
            commitActive,
            commitStreakCount,
            latestCommit,
            durationMins,
            allFailingRunsUrl,
        })
        const metadata = {
            event_type: INCIDENT_EVENT_TYPE,
            event_payload: { status: 'active', since, workflows, commitActive },
        }

        if (!active) {
            const posted = await slack.postMessage({ channel, ...message, metadata, unfurl_links: false })
            await slack.postMessage({
                channel,
                thread_ts: posted.ts,
                text: buildThreadReply({ created: workflows, commitStarted: commitActive }),
            })
            action = 'create'
        } else {
            await slack.update({ channel, ts: active.ts, ...message, metadata, unfurl_links: false })
            // Diff against the previous set to decide whether the timeline moved.
            const prevWorkflows = normalizeWorkflows(active.payload?.workflows)
            const prevNames = new Set(prevWorkflows.map((w) => w.name))
            const currNames = new Set(workflows.map((w) => w.name))
            const added = workflows.filter((w) => !prevNames.has(w.name))
            const removed = prevWorkflows.filter((w) => !currNames.has(w.name))
            const commitStarted = commitActive && !active.payload?.commitActive
            if (added.length || removed.length || commitStarted) {
                await slack.postMessage({
                    channel,
                    thread_ts: active.ts,
                    text: buildThreadReply({ added, removed, commitStarted }),
                })
            }
            action = 'update'
        }
    } else if (active) {
        const since = active.payload?.since
        const durationMins = since ? Math.round((now.getTime() - new Date(since).getTime()) / 60000) : 0
        const previousWorkflows = normalizeWorkflows(active.payload?.workflows)
        const message = buildResolvedMessage({ previousWorkflows, durationMins })
        await slack.update({
            channel,
            ts: active.ts,
            ...message,
            metadata: { event_type: INCIDENT_EVENT_TYPE, event_payload: { status: 'resolved' } },
            unfurl_links: false,
        })
        await slack.postMessage({ channel, thread_ts: active.ts, text: buildRecoveryReply(durationMins) })
        action = 'resolve'
    }

    core.info(
        `Action: ${action} | blocking: ${blocking.map((b) => b.name).join(', ') || 'none'} | commit streak: ${commitStreakCount}`
    )
    core.setOutput('action', action)
    core.setOutput('blocking_count', String(blocking.length))
    core.setOutput('commit_streak', String(commitStreakCount))
}

module.exports.formatDuration = formatDuration
module.exports.fetchWorkflowRuns = fetchWorkflowRuns
