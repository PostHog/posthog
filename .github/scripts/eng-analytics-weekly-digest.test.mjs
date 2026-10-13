import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

const OVERVIEW = {
    billable_minutes: 700,
    billable_minutes_prev: 350,
    depot_ci_billable_minutes: 200,
    depot_ci_billable_minutes_prev: 100,
}
const CONTRACT_ENV = {
    POSTHOG_HOST: 'https://example.com',
    POSTHOG_PROJECT_ID: '1',
    POSTHOG_API_KEY: 'fake-posthog-token',
    ENG_ANALYTICS_SOURCE_ID: '',
    SLACK_BOT_TOKEN: 'fake-slack-token',
    SLACK_CHANNEL: 'fake-channel',
    DEPOT_TOKEN: 'fake-depot-token',
    DEPOT_CONTRACT_MINUTES: '10000',
    DEPOT_CONTRACT_START: '2026-01-01',
    DEPOT_CONTRACT_END: '2027-01-01',
    DRY_RUN: '',
    GITHUB_REPOSITORY: '',
    GITHUB_WORKFLOW_REF: '',
}
let importCount = 0

async function runDigest(t, { env = {}, usage = [9000, 700, 350], overview = OVERVIEW } = {}) {
    t.mock.timers.enable({ apis: ['Date'], now: new Date('2026-10-05T13:00:00Z') })
    const settings = { ...CONTRACT_ENV, ...env }
    const previousEnv = Object.fromEntries(Object.keys(settings).map((key) => [key, process.env[key]]))
    Object.assign(process.env, settings)
    const requests = []
    const logs = []
    let blocks
    let usageIndex = 0
    t.mock.method(console, 'info', (message) => logs.push(message))
    t.mock.method(console, 'warn', (message) => logs.push(message))
    t.mock.method(globalThis, 'fetch', async (url, options) => {
        const href = String(url)
        requests.push({ url: href, ...options })
        if (href.startsWith('https://example.com/')) {
            return Response.json(overview)
        }
        if (href.startsWith('https://api.depot.dev/')) {
            const value = usage[usageIndex++]
            if (value instanceof Error) {
                throw value
            }
            if (value instanceof Response) {
                return value
            }
            return Response.json(
                typeof value === 'number'
                    ? {
                          githubActionsJobs: [
                              { total: { minutesBilled: value / 2 } },
                              { total: { minutesBilled: value / 2 } },
                          ],
                      }
                    : value
            )
        }
        assert.equal(href, 'https://slack.com/api/chat.postMessage')
        blocks = JSON.parse(options.body).blocks
        return Response.json({ ok: true })
    })
    try {
        const { main } = await import(`./eng-analytics-weekly-digest.mjs?test=${++importCount}`)
        await main()
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

describe('weekly engineering analytics digest', () => {
    it('uses complete UTC weeks and sums billed minutes across repositories', async (t) => {
        const { blocks, requests } = await runDigest(t)
        const overviewUrl = new URL(requests[0].url)
        assert.equal(overviewUrl.searchParams.get('date_from'), '2026-09-28T00:00:00.000Z')
        assert.equal(overviewUrl.searchParams.get('date_to'), '2026-10-05T00:00:00.000Z')
        assert.equal(overviewUrl.searchParams.get('include_series'), 'false')
        assert.match(blocks[0].text.text, /2026-09-28 to 2026-10-04 UTC/)
        assert.deepEqual(
            requests
                .filter((request) => request.url.startsWith('https://api.depot.dev/'))
                .map((request) => JSON.parse(request.body)),
            [
                { startAt: '2026-01-01T00:00:00.000Z', endAt: '2026-10-05T00:00:00.000Z' },
                { startAt: '2026-09-28T00:00:00.000Z', endAt: '2026-10-05T00:00:00.000Z' },
                { startAt: '2026-09-21T00:00:00.000Z', endAt: '2026-09-28T00:00:00.000Z' },
            ]
        )
        assert.deepEqual(
            blocks[1].rows.at(-1).map((cell) => cell.text),
            ['Depot runner min, all repos', '700', '350', '+100.0%']
        )
        assert.match(blocks[2].text.text, /9,000 of 10,000/)
        assert.match(blocks[2].text.text, /run out around 2026-10-15, 78 days before/)
    })

    for (const [name, usage, expected] of [
        ['exhausted minutes', [10000, 700, 350], /The contract minutes are used up/],
        ['zero usage', [9000, 0, 350], /minutes are not counted here\.$/],
        ['omitted protobuf list', [9000, {}, 350], /minutes are not counted here\.$/],
        [
            'omitted protobuf zero',
            [9000, { githubActionsJobs: [{ total: {} }] }, 350],
            /minutes are not counted here\.$/,
        ],
    ]) {
        it(`handles ${name} without breaking the digest`, async (t) => {
            const { blocks } = await runDigest(t, { usage })
            assert.match(blocks[2].text.text, expected)
        })
    }

    for (const [name, env] of [
        ['missing token', { DEPOT_TOKEN: '' }],
        ['non-finite allowance', { DEPOT_CONTRACT_MINUTES: 'Infinity' }],
        ['invalid calendar date', { DEPOT_CONTRACT_START: '2026-02-30' }],
        ['future contract', { DEPOT_CONTRACT_START: '2026-10-06' }],
        ['expired contract', { DEPOT_CONTRACT_END: '2026-10-04' }],
    ]) {
        it(`posts the CI table without Depot data with ${name}`, async (t) => {
            const { blocks, requests } = await runDigest(t, { env })
            assert.equal(blocks.length, 2)
            assert.equal(requests.length, 2)
            assert.equal(blocks[1].rows[1][0].text, 'CI minutes')
        })
    }

    for (const [name, failedUsage] of [
        ['HTTP failure', new Response('confidential-response', { status: 503 })],
        ['invalid JSON', new Response('confidential-response')],
        ['network failure', new Error('confidential-response')],
        ['missing totals', { githubActionsJobs: [{}] }],
        ['string minutes', { githubActionsJobs: [{ total: { minutesBilled: 'confidential-response' } }] }],
        ['negative minutes', { githubActionsJobs: [{ total: { minutesBilled: -1 } }] }],
        ['non-finite protobuf float', { githubActionsJobs: [{ total: { minutesBilled: 'Infinity' } }] }],
    ]) {
        it(`omits unavailable Depot data and protects logs on ${name}`, async (t) => {
            const { blocks, logs } = await runDigest(t, { usage: [failedUsage, 700, 350] })
            assert.equal(blocks.length, 2)
            assert.doesNotMatch(JSON.stringify(logs), /confidential-response/)
            assert.ok(logs.length > 0)
        })
    }

    it('hides Depot figures and never posts to Slack in a dry run', async (t) => {
        const { blocks, logs, requests } = await runDigest(t, { env: { DRY_RUN: 'true' }, usage: [9876, 654, 321] })
        assert.equal(blocks, undefined)
        assert.ok(requests.every((request) => !request.url.startsWith('https://slack.com/')))
        assert.doesNotMatch(JSON.stringify(logs), /9876|9,876|654|321|10,000|2027-01-01/)
        assert.match(logs[0], /hidden in dry runs/)
    })

    it('omits the Depot CI row until both backend windows are available', async (t) => {
        const { blocks } = await runDigest(t, { overview: { ...OVERVIEW, depot_ci_billable_minutes_prev: null } })
        assert.ok(blocks[1].rows.every((row) => row[0].text !== '└ Depot CI'))
    })
})
