const { setTimeout: sleep } = require('node:timers/promises')

const FIRST_ATTEMPT = 1
const INITIAL_FAILURES = 3
const REPEAT_INTERVAL = 10
const RUNS_PER_PAGE = 100
const HISTORY_PAGES = 10
const MAX_RUN_DURATION_MS = 6 * 60 * 60 * 1000
const STALE_INDEX_RETRY_MS = 2000
const SLACK_CHANNEL = 'C0B11J29GP9'

const ALIAS_JOB = 'Publish ordered image alias'
const aliasConsequence = (image, deploys = 'deploys') =>
    `A missing or unverified ordered alias can leave Kargo without Freight for ${image}, so ${deploys} stay on the previous build.`
const LANES = {
    'Container Images CD': [
        { job: ALIAS_JOB, image: 'PostHog', consequence: aliasConsequence('the PostHog image') },
        {
            job: 'Publish eligible shared-image channels',
            image: 'PostHog shared-image channels',
            consequence:
                'Shared-image channel publication did not complete cleanly. Workers on channels that were not verified may remain on their previous image. Check the linked run for the failure and any channel results.',
        },
    ],
    'Build and deploy node container image': [
        { job: ALIAS_JOB, image: 'Node.js', consequence: aliasConsequence('the Node.js image') },
    ],
    'Build and deploy rust container images': ['ghcr', 'ecr'].map((registry) => ({
        job: `publish ordered image aliases (${registry})`,
        image: `Rust (${registry})`,
        consequence: aliasConsequence(`the Rust images in ${registry.toUpperCase()}`, 'deploys using that registry'),
    })),
    'Credentials Service Container Image CD': [
        {
            job: ALIAS_JOB,
            image: 'Credentials service',
            consequence: aliasConsequence('the credentials service image in the affected registry', 'deploys using that registry'),
        },
    ],
}

function laneConclusion(jobs, jobName) {
    const conclusion = jobs.find((job) => job.name === jobName)?.conclusion
    if (conclusion === 'timed_out') {
        return 'failure'
    }
    if (conclusion === 'success' || conclusion === 'failure') {
        return conclusion
    }
}

async function streakMessages({ run, jobs }, olderRuns) {
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

    for await (const older of olderRuns) {
        for (const streak of pending) {
            if (streak.settled) {
                continue
            }
            const conclusion = older && laneConclusion(older.jobs, streak.job)
            if (!older || conclusion === 'success') {
                streak.settled = true
            } else if (conclusion === 'failure') {
                streak.count++
                streak.firstFailure = older.run
                if (streak.conclusion === 'success' && streak.count === INITIAL_FAILURES) {
                    streak.settled = true
                }
            }
        }
        if (pending.every((streak) => streak.settled)) {
            break
        }
    }

    for (const { image, job, consequence, conclusion, count, firstFailure, settled } of pending) {
        if (count < INITIAL_FAILURES) {
            continue
        }
        const lane = `${image} (${run.name})`
        if (conclusion === 'success') {
            messages.push(`${job} for ${lane} succeeded after at least ${INITIAL_FAILURES} consecutive failures (<${run.html_url}|successful run>).`)
        } else if (settled && (count - INITIAL_FAILURES) % REPEAT_INTERVAL === 0) {
            messages.push(
                `${lane} failed in ${count} consecutive runs (<${run.html_url}|newest failure>, <${firstFailure.html_url}|first failure>). ${consequence}`
            )
        }
    }
    return messages
}

function newestFirst(a, b) {
    return Date.parse(b.updated_at) - Date.parse(a.updated_at) || b.id - a.id
}

async function firstAttemptRun(actions, coordinates, run) {
    if (run.run_attempt > FIRST_ATTEMPT) {
        const { data } = await actions.getWorkflowRunAttempt({
            ...coordinates,
            run_id: run.id,
            attempt_number: FIRST_ATTEMPT,
        })
        return { ...data, jobsAttempt: FIRST_ATTEMPT }
    }
    return run
}

async function* loadOlderRuns(actions, coordinates, trigger, readJobs, delay) {
    const readPage = async (page) => {
        const { data } = await actions.listWorkflowRuns({
            ...coordinates,
            workflow_id: trigger.workflow_id,
            branch: 'master',
            event: 'push',
            status: 'completed',
            created: `<=${trigger.updated_at}`,
            per_page: RUNS_PER_PAGE,
            page,
        })
        return data.workflow_runs
    }

    const seen = new Set([trigger.id])
    const waiting = new Set()
    let oldestFetchedCreation = Infinity
    for (let page = 1; page <= HISTORY_PAGES; page++) {
        let runs = await readPage(page)
        if (page === 1 && !runs.some((run) => run.id === trigger.id)) {
            await delay(STALE_INDEX_RETRY_MS)
            runs = await readPage(page)
            if (!runs.some((run) => run.id === trigger.id)) {
                throw new Error(`Stale Actions history: run ${trigger.id} is missing from the first page`)
            }
        }

        for (const listedRun of runs) {
            oldestFetchedCreation = Math.min(oldestFetchedCreation, Date.parse(listedRun.created_at))
            if (seen.has(listedRun.id)) {
                continue
            }
            seen.add(listedRun.id)
            const run = await firstAttemptRun(actions, coordinates, listedRun)
            if (newestFirst(run, trigger) > 0) {
                waiting.add(run)
            }
        }

        const exhausted = runs.length < RUNS_PER_PAGE
        const latestUnreadCompletion = exhausted ? -Infinity : oldestFetchedCreation + MAX_RUN_DURATION_MS
        const ready = []
        for (const run of waiting) {
            if (Date.parse(run.updated_at) > latestUnreadCompletion) {
                waiting.delete(run)
                ready.push(run)
            }
        }
        for (const run of ready.sort(newestFirst)) {
            yield { run, jobs: await readJobs(run) }
        }
        if (exhausted) {
            yield null
            return
        }
    }
}

module.exports = async (
    { context, github },
    { fetch: send = fetch, token = process.env.SLACK_BOT_TOKEN, delay = sleep } = {}
) => {
    const run = context.payload.workflow_run
    if (run.run_attempt !== FIRST_ATTEMPT) {
        return
    }

    const actions = github.rest.actions
    const coordinates = context.repo
    const readJobs = async ({ id, jobsAttempt }) => {
        const jobs = []
        const perPage = 100
        const method = jobsAttempt ? 'listJobsForWorkflowRunAttempt' : 'listJobsForWorkflowRun'
        const params = { ...coordinates, run_id: id, per_page: perPage }
        if (jobsAttempt) {
            params.attempt_number = jobsAttempt
        }
        for (let page = 1; ; page++) {
            const { data } = await actions[method]({ ...params, page })
            jobs.push(...data.jobs)
            if (data.jobs.length < perPage || jobs.length >= data.total_count) {
                return jobs
            }
        }
    }
    const jobs = await readJobs({ ...run, jobsAttempt: FIRST_ATTEMPT })
    const messages = await streakMessages({ run, jobs }, loadOlderRuns(actions, coordinates, run, readJobs, delay))
    if (!messages.length) {
        return
    }
    if (!token) {
        throw new Error('Slack bot token is missing')
    }
    const result = await send('https://slack.com/api/chat.postMessage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ channel: SLACK_CHANNEL, text: messages.join('\n'), unfurl_links: false, unfurl_media: false }),
    })
    if (!result.ok) {
        throw new Error(`Slack chat.postMessage failed with HTTP ${result.status}`)
    }
    const data = await result.json()
    if (!data.ok) {
        throw new Error(`Slack chat.postMessage failed: ${data.error}`)
    }
}

module.exports.LANES = LANES
