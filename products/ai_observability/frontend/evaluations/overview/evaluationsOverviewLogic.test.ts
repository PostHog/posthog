import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { EvaluationApi, EvaluationResultApi } from '../../generated/api.schemas'
import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import { evaluationResultDrawerLogic } from './evaluationResultDrawerLogic'
import {
    evaluationsOverviewLogic,
    markEvaluationsOverviewStale,
    resetEvaluationsOverviewStale,
} from './evaluationsOverviewLogic'

const EMPTY_OVERVIEW = {
    start: '2026-10-01T00:00:00+00:00',
    end: '2026-10-15T00:00:00+00:00',
    previousStart: '2026-09-17T00:00:00+00:00',
    previousEnd: '2026-10-01T00:00:00+00:00',
    interval: 'day',
    buckets: [],
    evaluations: [],
    totals: { graded: 0, gradedComparison: null, gradedTrend: [], sentiment: null },
    passRateOverview: {
        entries: [],
        median: null,
        medianComparison: null,
        medianTrend: [],
    },
}

const evaluation = (id: string, directoryId: string | null): Partial<EvaluationApi> => ({
    id,
    name: `Evaluation ${id}`,
    directory_id: directoryId,
    enabled: true,
    status: 'active',
    status_reason: null,
    status_reason_detail: null,
    evaluation_type: 'llm_judge',
    evaluation_config: { prompt: 'Prompt' },
    output_type: 'boolean',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    created_by: null,
})

const row = (id: string, outputType: string, summary: EvaluationResultApi['summary']): EvaluationResultApi => ({
    id,
    name: `Evaluation ${id}`,
    directoryName: null,
    evaluationType: 'llm_judge',
    outputType,
    enabled: true,
    statusReason: null,
    createdBy: null,
    gradedCount: 10,
    previousGradedCount: null,
    notApplicableCount: 0,
    skippedCount: 0,
    lastRunAt: null,
    summary,
    trend: { values: [], volume: [] },
    change: null,
    lowEvidence: false,
    attentionReasons: [],
    bucketStatus: [],
    trackedCategory: null,
})

const SCALE = { min: 0, max: 10 }
const ROWS = [
    row('eval-a', 'boolean', { kind: 'pass_rate', passed: 8, failed: 2, previous: null, score: null }),
    row('eval-b', 'numeric', {
        kind: 'pass_rate',
        passed: 8,
        failed: 2,
        previous: null,
        score: { mean: 7, scale: SCALE },
    }),
    row('eval-c', 'numeric', { kind: 'score', score: { mean: 7, scale: SCALE }, previousMean: null }),
    row('eval-d', 'numeric', { kind: 'score', score: { mean: 7, scale: null }, previousMean: null }),
    row('eval-e', 'categorical', { kind: 'categories', multiple: false, categories: [], noCategoriesCount: 0 }),
]
const PASS_RATE = { kind: 'pass_rate', passed: 40, failed: 10, previous: null, score: null } as const
const SENTIMENT = { kind: 'sentiment', positive: 10, neutral: 10, negative: 30, previousNegativeShare: 40 } as const
const attentionRow = (
    id: string,
    reason: EvaluationResultApi['attentionReasons'][number] | null,
    summary: EvaluationResultApi['summary'],
    change: number | null
): EvaluationResultApi => ({
    ...row(id, 'boolean', summary),
    gradedCount: reason === 'errored' || reason === 'silent' ? 0 : 50,
    trend: { values: [50], volume: [50] },
    change: change === null ? null : { value: change, unit: 'pp', subject: null },
    attentionReasons: reason ? [reason] : [],
})
// A falling pass rate and a rising negative share are both worse, so the sentiment row is the worst regression.
const ATTENTION_ROWS = [
    attentionRow('healthy', null, PASS_RATE, 1),
    attentionRow('silent', 'silent', PASS_RATE, null),
    attentionRow('worse-5', 'worse', PASS_RATE, -5),
    attentionRow('worse-sentiment', 'worse', SENTIMENT, 20),
    attentionRow('worse-12', 'worse', PASS_RATE, -12),
    attentionRow('worse-8', 'worse', PASS_RATE, -8),
    attentionRow('errored', 'errored', PASS_RATE, null),
]

const HISTOGRAM = { scale: SCALE, buckets: [{ label: '7', count: 10 }] }

const PERIOD = 'date_from=2026-10-01&date_to=2026-10-14'

/** The clock the tests read. Only Date is faked, so kea breakpoints and network mocks keep real timers. */
const NOW = '2026-10-22T10:30:15Z'

/** A rolling range in hours as the request sends it: exact instants up to the current minute. */
function lastHours(hours: number): string {
    const end = dayjs.utc(NOW).startOf('minute')
    const instant = (value: dayjs.Dayjs): string => value.format('YYYY-MM-DDTHH:mm:ss[Z]')
    return `date_from=${instant(end.subtract(hours, 'hour'))}&date_to=${instant(end)}`
}

/** A details read as `<endpoint> <id> <query>`, without the period every read sends. */
function detailRequest(endpoint: string, id: string, url: string): string {
    const params = new URL(url).searchParams
    params.delete('date_from')
    params.delete('date_to')
    return `${endpoint} ${id} ${params.toString()}`.trim()
}

const FAILURES_QUERY = 'outcome=failed&limit=5'

describe('evaluationsOverviewLogic', () => {
    let requests: URLSearchParams[]
    let detailRequests: string[]
    let logic: ReturnType<typeof evaluationsOverviewLogic.build>

    beforeEach(async () => {
        resetEvaluationsOverviewStale()
        jest.useFakeTimers({
            now: new Date(NOW),
            doNotFake: [
                'hrtime',
                'nextTick',
                'performance',
                'queueMicrotask',
                'requestAnimationFrame',
                'cancelAnimationFrame',
                'requestIdleCallback',
                'cancelIdleCallback',
                'setImmediate',
                'clearImmediate',
                'setInterval',
                'clearInterval',
                'setTimeout',
                'clearTimeout',
            ],
        })
        requests = []
        detailRequests = []
        useMocks({
            get: {
                '/api/environments/:teamId/llm_analytics/provider_keys/': { results: [] },
                '/api/projects/:teamId/evaluations/': {
                    count: 3,
                    next: null,
                    results: [evaluation('eval-a', null), evaluation('eval-b', 'dir-1'), evaluation('eval-c', 'dir-1')],
                },
                '/api/projects/:teamId/evaluation_directories/': [],
                '/api/projects/:teamId/evaluations/:id/runs/': ({ params, request }) => {
                    detailRequests.push(detailRequest('runs', params.id as string, request.url))
                    return [200, { results: [] }]
                },
                '/api/projects/:teamId/evaluations/:id/score_distribution/': ({ params, request }) => {
                    detailRequests.push(detailRequest('score_distribution', params.id as string, request.url))
                    return [200, HISTOGRAM]
                },
                '/api/projects/:teamId/evaluations/overview/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    requests.push(params)
                    // The backend buckets a day or two by hour.
                    const oneDay = params.get('date_from') === params.get('date_to')
                    return [200, { ...EMPTY_OVERVIEW, evaluations: ROWS, interval: oneDay ? 'hour' : 'day' }]
                },
            },
        })
        initKeaTests()
        llmEvaluationsLogic.mount()
        llmEvaluationsLogic.actions.setDates('2026-10-01', '2026-10-14')
        logic = evaluationsOverviewLogic()
        logic.mount()
        await expectLogic(llmEvaluationsLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()
        requests = []
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    test.each([
        {
            name: 'scope change sends the picked evaluations',
            act: () => logic.actions.setPickedIds(['eval-a']),
            expected: [`${PERIOD}&evaluation_ids=eval-a`],
        },
        {
            name: 'several scope picks in a row read once',
            act: () => {
                logic.actions.setPickedIds(['eval-a'])
                logic.actions.setPickedIds(['eval-a', 'eval-b'])
            },
            expected: [`${PERIOD}&evaluation_ids=eval-a,eval-b`],
        },
        {
            name: 'date change sends the new period',
            act: () => llmEvaluationsLogic.actions.setDates('2026-09-01', '2026-09-30'),
            expected: ['date_from=2026-09-01&date_to=2026-09-30'],
        },
        {
            name: 'last 7 days sends the 7 whole days ending today',
            act: () => llmEvaluationsLogic.actions.setDates('-7d', null),
            expected: ['date_from=2026-10-16&date_to=2026-10-22'],
        },
        {
            name: 'last 2 weeks sends the 14 whole days ending today',
            act: () => llmEvaluationsLogic.actions.setDates('-2w', null),
            expected: ['date_from=2026-10-09&date_to=2026-10-22'],
        },
        {
            name: 'last 90 days fits the backend limit',
            act: () => llmEvaluationsLogic.actions.setDates('-90d', null),
            expected: ['date_from=2026-07-25&date_to=2026-10-22'],
        },
        {
            // Clocks fall back on November 1, so these 90 days are 2161 hours long.
            name: '90 days across a daylight saving change fit the backend limit',
            act: () => {
                teamLogic.actions.loadCurrentTeamSuccess({
                    ...teamLogic.values.currentTeam!,
                    timezone: 'America/New_York',
                })
                llmEvaluationsLogic.actions.setDates('2026-08-05', '2026-11-02')
            },
            expected: ['date_from=2026-08-05&date_to=2026-11-02'],
        },
        {
            name: 'last 24 hours sends exact instants',
            act: () => llmEvaluationsLogic.actions.setDates('-24h', null),
            expected: [lastHours(24)],
        },
        {
            name: 'this month sends whole days from its first day',
            act: () => llmEvaluationsLogic.actions.setDates('mStart', null),
            expected: ['date_from=2026-10-01&date_to=2026-10-22'],
        },
        {
            name: 'yesterday sends that whole day',
            act: () => llmEvaluationsLogic.actions.setDates('-1dStart', '-1dEnd'),
            expected: ['date_from=2026-10-21&date_to=2026-10-21'],
        },
        {
            name: 'last week starts on the first day of the project week',
            act: () => {
                teamLogic.actions.loadCurrentTeamSuccess({ ...teamLogic.values.currentTeam!, week_start_day: 1 })
                llmEvaluationsLogic.actions.setDates('-1wStart', '-1wEnd')
            },
            expected: ['date_from=2026-10-12&date_to=2026-10-18'],
        },
        {
            name: 'a period the backend refuses is not requested',
            act: () => llmEvaluationsLogic.actions.setDates('2026-01-01', '2026-09-30'),
            expected: [],
        },
        {
            name: 'opening a directory sends only its evaluations',
            act: () => llmEvaluationsLogic.actions.selectDirectory('dir-1'),
            expected: [`${PERIOD}&evaluation_ids=eval-b,eval-c`],
        },
        {
            name: 'a pick inside a directory narrows it',
            act: () => {
                llmEvaluationsLogic.actions.selectDirectory('dir-1')
                logic.actions.setPickedIds(['eval-c'])
            },
            expected: [`${PERIOD}&evaluation_ids=eval-b,eval-c`, `${PERIOD}&evaluation_ids=eval-c`],
        },
        {
            name: 'several edits in a row reload once past the cache',
            act: () => {
                llmEvaluationsLogic.actions.moveEvaluationSuccess('eval-a', 'dir-1')
                llmEvaluationsLogic.actions.toggleEvaluationEnabledSuccess('eval-b')
            },
            expected: [`${PERIOD}&refresh=true`],
        },
        {
            name: 'undo reloads past the cache',
            act: () => llmEvaluationsLogic.actions.restoreEvaluationSuccess(evaluation('eval-d', null) as any),
            expected: [`${PERIOD}&refresh=true`],
        },
        {
            name: 'reload skips the cache',
            act: () => logic.actions.reloadOverview(),
            expected: [`${PERIOD}&refresh=true`],
        },
        {
            name: 'returning after a save in the editor skips the cache',
            act: () => {
                logic.unmount()
                markEvaluationsOverviewStale()
                logic.mount()
            },
            expected: [`${PERIOD}&refresh=true`],
        },
        {
            name: 'after a save in a directory, leaving the directory skips the cache too',
            act: () => {
                llmEvaluationsLogic.actions.selectDirectory('dir-1')
                logic.unmount()
                markEvaluationsOverviewStale()
                logic.mount()
                llmEvaluationsLogic.actions.selectDirectory(null)
            },
            expected: [
                `${PERIOD}&evaluation_ids=eval-b,eval-c`,
                `${PERIOD}&evaluation_ids=eval-b,eval-c&refresh=true`,
                `${PERIOD}&refresh=true`,
            ],
        },
        {
            name: 'browser back from a directory drops the picks made in it',
            act: () => {
                llmEvaluationsLogic.actions.selectDirectory('dir-1')
                logic.actions.setPickedIds(['eval-c'])
                router.actions.push(router.values.location.pathname, {
                    ...router.values.searchParams,
                    directory: undefined,
                })
            },
            expected: [`${PERIOD}&evaluation_ids=eval-b,eval-c`, PERIOD],
        },
    ])('$name', async ({ act, expected }) => {
        act()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.map((params) => decodeURIComponent(params.toString()))).toEqual(expected)
    })

    it('reads an evaluation once when the pointer rests on its name twice', async () => {
        const drawerLogic = evaluationResultDrawerLogic()
        drawerLogic.mount()

        drawerLogic.actions.prefetchDetails('eval-b')
        await expectLogic(drawerLogic).toFinishAllListeners()
        drawerLogic.actions.prefetchDetails('eval-b')
        await expectLogic(drawerLogic).toFinishAllListeners()

        expect(detailRequests).toEqual([`runs eval-b ${FAILURES_QUERY}`, 'score_distribution eval-b'])
        expect(drawerLogic.values.details).toMatchObject({
            'eval-b/2026-10-01/2026-10-14': { status: 'ready' },
        })
    })

    it('loads the open drawer again when the period changes under it', async () => {
        const drawerLogic = evaluationResultDrawerLogic()
        drawerLogic.mount()
        drawerLogic.actions.openDrawer('eval-b')
        await expectLogic(drawerLogic).toFinishAllListeners()

        llmEvaluationsLogic.actions.setDates('2026-09-01', '2026-09-30')
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(drawerLogic).toFinishAllListeners()

        expect(detailRequests).toEqual([
            `runs eval-b ${FAILURES_QUERY}`,
            'score_distribution eval-b',
            `runs eval-b ${FAILURES_QUERY}`,
            'score_distribution eval-b',
        ])
        expect(drawerLogic.values.openDetails).toMatchObject({ status: 'ready' })
    })

    test.each([
        { dateFrom: '-14d', dateTo: null, expected: '"date_from":"2026-10-09","date_to":"2026-10-22"' },
        // Hourly buckets read a date-only end as midnight, which would drop the whole day.
        {
            dateFrom: '-1dStart',
            dateTo: '-1dEnd',
            expected: '"date_from":"2026-10-21","date_to":"2026-10-21T23:59:59"',
        },
    ])(
        'opens the same period in Explore as the overview shows from $dateFrom',
        async ({ dateFrom, dateTo, expected }) => {
            llmEvaluationsLogic.actions.setDates(dateFrom, dateTo)
            await expectLogic(logic).toFinishAllListeners()

            expect(decodeURIComponent(logic.values.exploreUrl ?? '')).toContain(expected)
        }
    )

    it('reloads an open directory after the list it waits for comes back', async () => {
        llmEvaluationsLogic.actions.selectDirectory('dir-1')
        await expectLogic(logic).toFinishAllListeners()
        requests = []
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        capture.mockClear()

        // The header Refresh reloads the list first, so the directory's evaluations are briefly unknown.
        llmEvaluationsLogic.actions.loadEvaluations()
        logic.actions.reloadOverview()
        await expectLogic(llmEvaluationsLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.map((params) => decodeURIComponent(params.toString()))).toEqual([
            `${PERIOD}&evaluation_ids=eval-b,eval-c&refresh=true`,
        ])
        expect(logic.values.overview).not.toBeNull()
        expect(capture.mock.calls.filter(([event]) => event === 'llma evaluation overview loaded')).toHaveLength(1)
    })

    test.each([
        { name: 'fails to reload', listFirst: true },
        { name: 'fails on the first load', listFirst: false },
    ])('offers a retry when the list an open directory waits for $name', async ({ listFirst }) => {
        llmEvaluationsLogic.actions.selectDirectory('dir-1')
        await expectLogic(logic).toFinishAllListeners()
        if (!listFirst) {
            llmEvaluationsLogic.actions.loadEvaluationsSuccess([])
        }
        useMocks({ get: { '/api/projects/:teamId/evaluations/': () => [500, {}] } })
        requests = []

        llmEvaluationsLogic.actions.loadEvaluations()
        logic.actions.reloadOverview()
        await expectLogic(llmEvaluationsLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests).toEqual([])
        expect(logic.values.request.notice).toBeNull()
        expect(logic.values.overviewFailure).toEqual('failed')

        useMocks({
            get: {
                '/api/projects/:teamId/evaluations/': {
                    count: 2,
                    next: null,
                    results: [evaluation('eval-b', 'dir-1'), evaluation('eval-c', 'dir-1')],
                },
            },
        })
        logic.actions.retryOverview()
        await expectLogic(llmEvaluationsLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.map((params) => decodeURIComponent(params.toString()))).toEqual([
            `${PERIOD}&evaluation_ids=eval-b,eval-c&refresh=true`,
        ])
    })

    test.each([
        {
            selector: 'tableRows' as const,
            expected: ['errored', 'worse-sentiment', 'worse-12', 'worse-8', 'worse-5', 'silent', 'healthy'],
        },
        { selector: 'chartedIds' as const, expected: ['worse-sentiment', 'worse-12', 'worse-8'] },
    ])('puts the worst regression first in $selector', async ({ selector, expected }) => {
        useMocks({
            get: {
                '/api/projects/:teamId/evaluations/overview/': () => [
                    200,
                    { ...EMPTY_OVERVIEW, buckets: ['2026-10-01'], evaluations: ATTENTION_ROWS },
                ],
            },
        })
        logic.actions.reloadOverview()
        await expectLogic(logic).toFinishAllListeners()

        const ids = logic.values[selector].map((item) => (typeof item === 'string' ? item : item.id))
        expect(ids).toEqual(expected)
    })

    it('keeps the selected dates on links to an evaluation', async () => {
        llmEvaluationsLogic.actions.setDates('-30d', null)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.evaluationUrl('eval-a', { evaluation_tab: 'backfills' })).toContain(
            'date_from=-30d&evaluation_tab=backfills'
        )
    })

    it('moves a rolling period up to the present on reload', async () => {
        llmEvaluationsLogic.actions.setDates('-24h', null)
        await expectLogic(logic).toFinishAllListeners()
        jest.setSystemTime(dayjs.utc(NOW).add(10, 'minute').toDate())

        logic.actions.reloadOverview()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.map((params) => params.get('date_to'))).toEqual([
            '2026-10-22T10:30:00Z',
            '2026-10-22T10:40:00Z',
        ])
    })

    test.each([
        { name: 'after the first read lands', settleFirst: true },
        { name: 'while the first read is still in flight', settleFirst: false },
    ])('reads the open drawer again past the cache on reload $name', async ({ settleFirst }) => {
        const drawerLogic = evaluationResultDrawerLogic()
        drawerLogic.mount()
        drawerLogic.actions.openDrawer('eval-b')
        if (settleFirst) {
            await expectLogic(drawerLogic).toFinishAllListeners()
        }

        logic.actions.reloadOverview()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(drawerLogic).toFinishAllListeners()

        expect(detailRequests).toEqual([
            `runs eval-b ${FAILURES_QUERY}`,
            'score_distribution eval-b',
            `runs eval-b refresh=true&${FAILURES_QUERY}`,
            'score_distribution eval-b refresh=true',
        ])
        expect(drawerLogic.values.openDetails).toMatchObject({ status: 'ready' })
    })

    test.each([
        {
            kind: 'boolean pass rate',
            id: 'eval-a',
            expected: [`runs eval-a ${FAILURES_QUERY}`],
            details: { recentFailures: [], scoreDistribution: null },
        },
        {
            kind: 'numeric pass rate',
            id: 'eval-b',
            expected: [`runs eval-b ${FAILURES_QUERY}`, 'score_distribution eval-b'],
            details: { recentFailures: [], scoreDistribution: HISTOGRAM },
        },
        {
            kind: 'score',
            id: 'eval-c',
            expected: ['score_distribution eval-c'],
            details: { recentFailures: null, scoreDistribution: HISTOGRAM },
        },
        {
            kind: 'score without bounds',
            id: 'eval-d',
            expected: [],
            details: { recentFailures: null, scoreDistribution: null },
        },
        {
            kind: 'categorical',
            id: 'eval-e',
            expected: [],
            details: { recentFailures: null, scoreDistribution: null },
        },
    ])('reads only the details a $kind evaluation has', async ({ id, expected, details }) => {
        const drawerLogic = evaluationResultDrawerLogic()
        drawerLogic.mount()

        drawerLogic.actions.openDrawer(id)
        await expectLogic(drawerLogic).toFinishAllListeners()

        expect(detailRequests).toEqual(expected)
        expect(drawerLogic.values.openDetails).toEqual({ status: 'ready', details })
    })

    it('shows the details as failed when either read fails', async () => {
        useMocks({ get: { '/api/projects/:teamId/evaluations/:id/score_distribution/': () => [500, {}] } })
        const drawerLogic = evaluationResultDrawerLogic()
        drawerLogic.mount()

        drawerLogic.actions.openDrawer('eval-b')
        await expectLogic(drawerLogic).toFinishAllListeners()

        expect(drawerLogic.values.openDetails).toEqual({ status: 'error', failure: 'failed' })
    })
})
