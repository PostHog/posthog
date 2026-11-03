import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

const OVERVIEW = {
    merged_pr_count: 100,
    merged_pr_count_prev: 70,
    median_ready_to_merge_seconds: 3600,
    median_ready_to_merge_seconds_prev: 7200,
}
const ENV = {
    POSTHOG_HOST: 'https://example.com',
    POSTHOG_PROJECT_ID: '1',
    POSTHOG_API_KEY: 'fake-posthog-token',
    ENG_ANALYTICS_SOURCE_ID: '',
    SLACK_BOT_TOKEN: 'fake-slack-token',
    SLACK_CHANNEL: 'fake-channel',
    DEPOT_TOKEN: 'fake-depot-token',
    DEPOT_CONTRACT_USD: '60000',
    DEPOT_CONTRACT_START: '2026-01-01',
    DEPOT_CONTRACT_END: '2027-01-01',
    DRY_RUN: '',
    GITHUB_REPOSITORY: 'PostHog/posthog',
    GITHUB_WORKFLOW_REF: '',
}
const WEEK = '2026-09-28T00:00:00.000Z'
const PRIOR_WEEK = '2026-09-21T00:00:00.000Z'
const CONTRACT = '2026-01-01T00:00:00.000Z'
// Runners $600 ($400 in this repository), builds $400, Depot CI $1,100 ($1,000 here): $2,100.
// The week before: runners $200, builds $200, Depot CI $500: $900. The contract so far: $50,000.
const DEPOT_USAGE = {
    [WEEK]: {
        githubActionsJobs: [
            { repo: 'PostHog/posthog', total: { minutesBilled: 100_000 } },
            { repo: 'PostHog/other', total: { minutesBilled: 50_000 } },
        ],
        containerBuild: [{ minutesBilled: 10_000 }],
    },
    [PRIOR_WEEK]: {
        githubActionsJobs: [{ repo: 'PostHog/posthog', total: { minutesBilled: 50_000 } }],
        containerBuild: [{ minutesBilled: 5_000 }],
    },
    [CONTRACT]: {
        githubActionsJobs: [{ repo: 'PostHog/posthog', total: { minutesBilled: 10_000_000 } }],
        containerBuild: [{ minutesBilled: 100_000 }],
    },
}
const DEPOT_CI_USAGE = {
    [WEEK]: [
        { repo: 'posthog/posthog', estimated_cost_usd: 1000 },
        { repo: 'posthog/posthog-private', estimated_cost_usd: 100 },
    ],
    [PRIOR_WEEK]: [{ repo: 'posthog/posthog', estimated_cost_usd: 500 }],
    [CONTRACT]: [{ repo: 'posthog/posthog', estimated_cost_usd: 6000 }],
}
let importCount = 0

async function runDigest(t, { env = {}, depotUsage = DEPOT_USAGE, depotCiUsage = DEPOT_CI_USAGE } = {}) {
    t.mock.timers.enable({ apis: ['Date', 'setTimeout'], now: new Date('2026-10-05T13:00:00Z') })
    const settings = { ...ENV, ...env }
    const previousEnv = Object.fromEntries(Object.keys(settings).map((key) => [key, process.env[key]]))
    Object.assign(process.env, settings)
    const requests = []
    const logs = []
    let blocks
    t.mock.method(console, 'info', (message) => logs.push(message))
    t.mock.method(console, 'warn', (message) => logs.push(message))
    t.mock.method(globalThis, 'fetch', async (url, options) => {
        const href = String(url)
        requests.push({ url: href, ...options })
        if (href.startsWith('https://example.com/')) {
            const parsed = new URL(href)
            if (parsed.pathname.endsWith('/depot_ci_usage/')) {
                const usage = depotCiUsage[parsed.searchParams.get('date_from')]
                return usage instanceof Response ? usage : Response.json(usage)
            }
            return Response.json(OVERVIEW)
        }
        if (href.startsWith('https://api.depot.dev/')) {
            const answer = depotUsage[JSON.parse(options.body).startAt]
            const usage = Array.isArray(answer) ? answer.shift() : answer
            if (usage instanceof Error) {
                throw usage
            }
            return usage instanceof Response ? usage : Response.json(usage)
        }
        assert.equal(href, 'https://slack.com/api/chat.postMessage')
        blocks = JSON.parse(options.body).blocks
        return Response.json({ ok: true })
    })
    try {
        const { main } = await import(`./eng-analytics-weekly-digest.mjs?test=${++importCount}`)
        let settled = false
        const run = main().finally(() => {
            settled = true
        })
        while (!settled) {
            await new Promise((resolve) => setImmediate(resolve))
            t.mock.timers.tick(30_000)
        }
        await run
        return { blocks, logs, requests }
    } finally {
        for (const [key, value] of Object.entries(previousEnv)) {
            if (value === undefined) {
                delete process.env[key]
            } else {
                process.env[key] = value
            }
        }
    }
}

function tableText(blocks) {
    return blocks[1].rows.slice(1).map((row) => row.map((cell) => cell.text))
}

describe('weekly engineering analytics digest', () => {
    for (const [name, override] of [
        ['', {}],
        [
            ' after a transient Depot failure',
            { depotUsage: { ...DEPOT_USAGE, [WEEK]: [new Response('', { status: 503 }), DEPOT_USAGE[WEEK]] } },
        ],
    ]) {
        it(`reports Depot spend for complete UTC weeks and the contract${name}`, async (t) => {
            const { blocks, requests } = await runDigest(t, override)
            const overviewUrl = new URL(requests.find((request) => request.url.includes('/repo_overview/')).url)
            assert.equal(overviewUrl.searchParams.get('date_from'), WEEK)
            assert.equal(overviewUrl.searchParams.get('date_to'), '2026-10-05T00:00:00.000Z')
            assert.equal(overviewUrl.searchParams.get('repo'), 'PostHog/posthog')
            assert.match(blocks[0].text.text, /2026-09-28 to 2026-10-04 UTC/)
            assert.deepEqual(tableText(blocks), [
                ['Depot spend', '$2,100', '$900', '+133.3%'],
                ['└ runners', '$600', '$200', '+200.0%'],
                ['└ Depot CI', '$1,100', '$500', '+120.0%'],
                ['└ container builds', '$400', '$200', '+100.0%'],
                ['$ / merged PR', '$14', '$10', '+40.0%'],
                ['merged PRs', '100', '70', '+42.9%'],
                ['ready→merge median', '1h', '2h', '-50.0%'],
            ])
            assert.equal(blocks[2].text.text, 'Depot CI counts posthog/posthog, posthog/posthog-private.')
            assert.match(blocks[3].text.text, /\$50,000 of \$60,000 used through 2026-10-04/)
            assert.match(
                blocks[3].text.text,
                /runs out around 2026-11-07, 55 days before the contract ends on 2027-01-01\.$/
            )
        })
    }

    for (const [name, allowance, expected] of [
        ['a used-up contract', '50000', /The contract is used up\.$/],
        ['a contract that lasts', '1000000', /it lasts until the contract ends on 2027-01-01\.$/],
    ]) {
        it(`describes ${name}`, async (t) => {
            const { blocks } = await runDigest(t, { env: { DEPOT_CONTRACT_USD: allowance } })
            assert.match(blocks[3].text.text, expected)
        })
    }

    for (const [name, override] of [
        ['the contract variables are missing', { env: { DEPOT_CONTRACT_USD: '' } }],
        [
            'the contract read fails',
            {
                depotCiUsage: {
                    ...DEPOT_CI_USAGE,
                    [CONTRACT]: Response.json({ detail: 'Not found.' }, { status: 404 }),
                },
            },
        ],
    ]) {
        it(`posts spend without the contract sentence when ${name}`, async (t) => {
            const { blocks } = await runDigest(t, override)
            assert.equal(tableText(blocks)[0][0], 'Depot spend')
            assert.ok(blocks.every((block) => !block.text?.text.startsWith('Depot contract')))
        })
    }

    for (const [name, override] of [
        [
            'a Depot HTTP failure',
            { depotUsage: { ...DEPOT_USAGE, [WEEK]: new Response('confidential-response', { status: 503 }) } },
        ],
        ['invalid Depot JSON', { depotUsage: { ...DEPOT_USAGE, [WEEK]: new Response('confidential-response') } }],
        ['a Depot network failure', { depotUsage: { ...DEPOT_USAGE, [WEEK]: new Error('confidential-response') } }],
        [
            'negative Depot minutes',
            { depotUsage: { ...DEPOT_USAGE, [PRIOR_WEEK]: { githubActionsJobs: [{ total: { minutesBilled: -1 } }] } } },
        ],
        [
            'a non-JSON depot_ci_usage response',
            {
                depotCiUsage: {
                    ...DEPOT_CI_USAGE,
                    [WEEK]: new Response('confidential-response', { status: 400 }),
                },
            },
        ],
        ['a missing token', { env: { DEPOT_TOKEN: '' } }],
    ]) {
        it(`posts without spend on ${name} and keeps Depot data out of the logs`, async (t) => {
            const { blocks, logs } = await runDigest(t, override)
            assert.deepEqual(
                tableText(blocks).map((row) => row[0]),
                ['merged PRs', 'ready→merge median']
            )
            assert.equal(blocks.length, 2)
            assert.doesNotMatch(JSON.stringify(logs), /confidential-response/)
            assert.ok(logs.length > 0)
        })
    }

    it('hides spend and never posts to Slack in a dry run', async (t) => {
        const { blocks, logs, requests } = await runDigest(t, { env: { DRY_RUN: 'true' } })
        assert.equal(blocks, undefined)
        assert.ok(requests.every((request) => !request.url.startsWith('https://slack.com/')))
        assert.doesNotMatch(JSON.stringify(logs), /\$[0-9]|60,000|2027-01-01/)
        assert.match(logs[0], /hidden in dry runs/)
    })
})
