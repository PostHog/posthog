import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { EvaluationApi } from '../../generated/api.schemas'
import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import { evaluationResultDrawerLogic } from './evaluationResultDrawerLogic'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

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

const PERIOD = 'date_from=2026-10-01&date_to=2026-10-14'

/** The clock the tests read. Only Date is faked, so kea breakpoints and network mocks keep real timers. */
const NOW = '2026-10-22T10:30:15Z'

/** A rolling range in hours as the request sends it: exact instants up to the current minute. */
function lastHours(hours: number): string {
    const end = dayjs.utc(NOW).startOf('minute')
    const instant = (value: dayjs.Dayjs): string => value.format('YYYY-MM-DDTHH:mm:ss[Z]')
    return `date_from=${instant(end.subtract(hours, 'hour'))}&date_to=${instant(end)}`
}

describe('evaluationsOverviewLogic', () => {
    let requests: URLSearchParams[]
    let detailRequests: string[]
    let logic: ReturnType<typeof evaluationsOverviewLogic.build>

    beforeEach(async () => {
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
                '/api/projects/:teamId/evaluations/:id/overview_details/': ({ params, request }) => {
                    const refresh = new URL(request.url).searchParams.get('refresh') === 'true'
                    detailRequests.push(`${params.id}${refresh ? ' refresh' : ''}`)
                    return [
                        200,
                        {
                            evaluationId: params.id,
                            start: '2026-10-01T00:00:00+00:00',
                            end: '2026-10-15T00:00:00+00:00',
                            recentFailures: [],
                            scoreDistribution: null,
                        },
                    ]
                },
                '/api/projects/:teamId/evaluations/overview/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    requests.push(params)
                    // The backend buckets a day or two by hour.
                    const oneDay = params.get('date_from') === params.get('date_to')
                    return [200, { ...EMPTY_OVERVIEW, interval: oneDay ? 'hour' : 'day' }]
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

        expect(detailRequests).toEqual(['eval-b'])
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

        expect(detailRequests).toEqual(['eval-b', 'eval-b'])
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

        // The header Refresh reloads the list first, so the directory's evaluations are briefly unknown.
        llmEvaluationsLogic.actions.loadEvaluations()
        logic.actions.reloadOverview()
        await expectLogic(llmEvaluationsLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.map((params) => decodeURIComponent(params.toString()))).toEqual([
            `${PERIOD}&evaluation_ids=eval-b,eval-c&refresh=true`,
        ])
        expect(logic.values.overview).not.toBeNull()
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

    it('reads the open drawer again past the cache on reload', async () => {
        const drawerLogic = evaluationResultDrawerLogic()
        drawerLogic.mount()
        drawerLogic.actions.openDrawer('eval-b')
        await expectLogic(drawerLogic).toFinishAllListeners()

        logic.actions.reloadOverview()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(drawerLogic).toFinishAllListeners()

        expect(detailRequests).toEqual(['eval-b', 'eval-b refresh'])
    })
})
