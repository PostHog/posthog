const INITIAL_FAILURES = 3
const REPEAT_INTERVAL = 10
const HISTORY_LIMIT = 100
const SLACK_CHANNEL = 'C0B11J29GP9'

const ALIAS_JOB = 'Publish ordered image alias'
const LANES = {
    'Container Images CD': [
        { job: ALIAS_JOB, image: 'PostHog' },
        { job: 'Publish eligible shared-image channels', image: 'PostHog shared-image channels' },
    ],
    'Build and deploy node container image': [{ job: ALIAS_JOB, image: 'Node.js' }],
    'Build and deploy rust container images': ['ghcr', 'ecr'].map((registry) => ({
        job: `publish ordered image aliases (${registry})`,
        image: `Rust (${registry})`,
    })),
    'Credentials Service Container Image CD': [{ job: ALIAS_JOB, image: 'Credentials service' }],
}

function laneConclusion(jobs, jobName) {
    const conclusion = jobs.find((job) => job.name === jobName)?.conclusion
    if (conclusion === 'success' || conclusion === 'failure') {
        return conclusion
    }
}

async function streakMessages({ run, jobs }, loadHistory) {
    const pending = (LANES[run.name] ?? []).flatMap((lane) => {
        const conclusion = laneConclusion(jobs, lane.job)
        if (!conclusion) {
            return []
        }
        return [
            {
                ...lane,
                conclusion,
                count: conclusion === 'failure' ? 1 : 0,
                firstFailure: run,
                settled: false,
            },
        ]
    })
    const messages = []
    if (!pending.length) {
        return messages
    }

    const { olderRuns, reachedHistoryStart } = await loadHistory()
    for await (const { run: olderRun, jobs: olderJobs } of olderRuns) {
        for (const streak of pending) {
            if (streak.settled) {
                continue
            }
            const conclusion = laneConclusion(olderJobs, streak.job)
            if (conclusion === 'success') {
                streak.settled = true
            } else if (conclusion === 'failure') {
                streak.count++
                streak.firstFailure = olderRun
                if (streak.conclusion === 'success' && streak.count === INITIAL_FAILURES) {
                    streak.settled = true
                }
            }
        }
        if (pending.every((streak) => streak.settled)) {
            break
        }
    }

    for (const { image, conclusion, count, firstFailure, settled } of pending) {
        if (count < INITIAL_FAILURES) {
            continue
        }
        const lane = `${image} (${run.name})`
        if (conclusion === 'success') {
            messages.push(`${lane} recovered in <${run.html_url}|this run>.`)
        } else if ((settled || reachedHistoryStart) && (count - INITIAL_FAILURES) % REPEAT_INTERVAL === 0) {
            messages.push(
                `${lane} ordered tagging failed in ${count} consecutive runs (<${run.html_url}|newest failure>, <${firstFailure.html_url}|first failure>). Without the ordered alias, Kargo creates no Freight for the image and deploys stay on the previous build.`
            )
        }
    }
    return messages
}

function newestFirst(a, b) {
    return Date.parse(b.updated_at) - Date.parse(a.updated_at) || b.id - a.id
}

async function loadOlderRuns(actions, coordinates, trigger, readJobs) {
    const { data } = await actions.listWorkflowRuns({
        ...coordinates,
        workflow_id: trigger.workflow_id,
        branch: 'master',
        event: 'push',
        status: 'completed',
        created: `<=${trigger.updated_at}`,
        per_page: HISTORY_LIMIT,
    })
    const runs = data.workflow_runs
        .filter((run) => run.id !== trigger.id && run.conclusion !== 'cancelled' && newestFirst(run, trigger) > 0)
        .sort(newestFirst)

    async function* olderRuns() {
        for (const run of runs) {
            yield { run, jobs: await readJobs(run) }
        }
    }

    return { olderRuns: olderRuns(), reachedHistoryStart: data.total_count <= HISTORY_LIMIT }
}

module.exports = async ({ context, github }, { fetch: send = fetch, token = process.env.SLACK_BOT_TOKEN } = {}) => {
    const run = context.payload.workflow_run
    if (run.run_attempt !== 1 || run.conclusion === 'cancelled') {
        return
    }

    const actions = github.rest.actions
    const coordinates = context.repo
    const readJobs = async ({ id }) => {
        const { data } = await actions.listJobsForWorkflowRun({ ...coordinates, run_id: id, per_page: 100 })
        return data.jobs
    }
    const jobs = await readJobs(run)
    const messages = await streakMessages({ run, jobs }, () => loadOlderRuns(actions, coordinates, run, readJobs))

    for (const text of messages) {
        if (!token) {
            throw new Error('Slack bot token is missing')
        }
        const result = await send('https://slack.com/api/chat.postMessage', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json; charset=utf-8', Authorization: `Bearer ${token}` },
            body: JSON.stringify({ channel: SLACK_CHANNEL, text, unfurl_links: false, unfurl_media: false }),
        })
        const data = await result.json()
        if (!result.ok || !data.ok) {
            throw new Error(`Slack chat.postMessage failed: ${data.error || result.status}`)
        }
    }
}
