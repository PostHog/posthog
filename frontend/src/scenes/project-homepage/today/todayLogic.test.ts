import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { makeReport } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'

import { todayHighlightsLogic } from './todayHighlightsLogic'
import { MORE_REPORTS_PAGE_SIZE, TOP_REPORT_COUNT, todayLogic } from './todayLogic'
import { isSampleReportId } from './todaySampleReports'
import { makeHighlightItem, makeHighlights } from './todayTestFixtures'
import { todayVerdictLogic } from './todayVerdictLogic'

describe('todayLogic', () => {
    let listResponse: [number, any]
    let listParams: URLSearchParams | null
    let highlightResponses: [number, any][]
    let highlightCalls: number

    beforeEach(() => {
        highlightResponses = [[200, makeHighlights()]]
        listResponse = [200, { results: [], count: 0 }]
        highlightCalls = 0
        listParams = null
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/for_you/': ({ request }) => {
                    listParams = new URL(request.url).searchParams
                    return listResponse
                },
                '/api/projects/:team_id/today/highlights/': () => {
                    highlightCalls += 1
                    return highlightResponses.length > 1 ? highlightResponses.shift()! : highlightResponses[0]
                },
            },
            post: {
                '/api/projects/:team_id/signals/reports/:id/state/': () => [200, {}],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('sends the Inbox ranking label events for the reports the home shows and acts on', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        const report = makeReport({ id: 'a' })
        listResponse = [200, { results: [report], count: 1 }]
        const logic = todayLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        // A reload of the same list does not impress its reports again.
        logic.actions.loadTopReports()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.reportOpened(report, 'list')
        todayVerdictLogic.actions.setReportVerdict(
            { reportId: 'a', title: 'Signup form rejects emails', hasOpenPullRequest: false },
            'dismiss',
            'briefing'
        )
        await expectLogic(todayVerdictLogic).toFinishAllListeners()

        const inboxEvents = capture.mock.calls.filter(([event]) => event.startsWith('Inbox '))
        expect(inboxEvents).toHaveLength(3)
        expect(inboxEvents).toEqual(
            expect.arrayContaining([
                [
                    'Inbox reports impressed',
                    expect.objectContaining({
                        surface: 'today',
                        list: 'briefing',
                        impressions: [expect.objectContaining({ report_id: 'a', rank: 1 })],
                    }),
                    undefined,
                ],
                [
                    'Inbox report opened',
                    expect.objectContaining({ report_id: 'a', surface: 'today', list: 'briefing', rank: 1 }),
                    undefined,
                ],
                [
                    'Inbox report action',
                    expect.objectContaining({ report_id: 'a', action_type: 'dismiss', surface: 'today' }),
                    undefined,
                ],
            ])
        )
    })

    it('ranks the report list events by the position the list shows them in', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        const [a, b] = [makeReport({ id: 'a', priority: 'P2' }), makeReport({ id: 'b', priority: 'P1' })]
        listResponse = [200, { results: [a, b], count: 2 }]
        const logic = todayLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.reportOpened(b, 'list')

        const events = capture.mock.calls.filter(([event]) => event.startsWith('Inbox '))
        expect(events).toEqual([
            [
                'Inbox reports impressed',
                expect.objectContaining({
                    impressions: [
                        expect.objectContaining({ report_id: 'a', rank: 1 }),
                        expect.objectContaining({ report_id: 'b', rank: 2 }),
                    ],
                }),
                undefined,
            ],
            ['Inbox report opened', expect.objectContaining({ report_id: 'b', list: 'briefing', rank: 2 }), undefined],
        ])
    })

    it('sends one preview event when a report row opens in place, and none when it closes', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        listResponse = [200, { results: [makeReport({ id: 'a' })], count: 1 }]
        const logic = todayLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.toggleReportRow('a', 'a')
        expect(logic.values.expandedReportRows).toEqual({ a: true })
        logic.actions.toggleReportRow('a', 'a')
        expect(logic.values.expandedReportRows).toEqual({})

        expect(capture.mock.calls.filter(([event]) => event === 'today report previewed')).toEqual([
            ['today report previewed', expect.objectContaining({ list: 'team', report_id: 'a', surface: 'list' })],
        ])
    })

    it.each([
        ['passes the refresh time', new Date('2026-10-01T05:59:45Z'), null],
        ['sleeps through the refresh time', new Date('2026-09-30T14:00:00Z'), new Date('2026-10-01T14:00:00Z')],
    ])('reloads the highlights when an open tab %s', async (_name, start, wakeAt) => {
        jest.useFakeTimers()
        jest.setSystemTime(start)
        const item = makeHighlightItem()
        highlightResponses = [
            [200, makeHighlights({ items: [item], refresh_at: '2026-10-01T06:00:00Z' })],
            [200, makeHighlights({ items: [item], day: '2026-10-01', refresh_at: '2026-10-02T06:00:00Z' })],
        ]
        const logic = todayLogic()
        logic.mount()
        const highlightsLoaded = todayHighlightsLogic.actionTypes.loadHighlightsSuccess
        await expectLogic(logic).toDispatchActions([highlightsLoaded])
        todayHighlightsLogic.actions.hideHighlight(item, 0)
        expect(logic.values.doneHighlightKeys).toEqual(['alert:a'])

        await expectLogic(logic, () => {
            if (wakeAt) {
                jest.setSystemTime(wakeAt)
            }
            jest.advanceTimersByTime(30_000)
        })
            .toDispatchActions(['tick', 'loadHighlights', highlightsLoaded])
            .toMatchValues({ doneHighlightKeys: [], forYouHighlights: [item] })
        expect(highlightCalls).toBe(2)

        await jest.advanceTimersByTimeAsync(30_000)
        expect(highlightCalls).toBe(2)
    })

    it('asks for the top reports for the person and counts the rest', async () => {
        const reports = [makeReport({ id: 'a' }), makeReport({ id: 'b' })]
        listResponse = [200, { results: reports, count: 9 }]
        const logic = todayLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ reports, moreReportCount: 7 })
        expect(Object.fromEntries(listParams!.entries())).toEqual({
            limit: String(TOP_REPORT_COUNT),
            include_unowned: 'false',
        })
    })

    it('pages through the reports past the list without the ones it shows, and starts over when the list shows other reports', async () => {
        const page = (prefix: string, length: number): ReturnType<typeof makeReport>[] =>
            Array.from({ length }, (_, index) => makeReport({ id: `${prefix}${index}` }))
        listResponse = [200, { results: [makeReport({ id: 'a' })], count: 5 }]
        const logic = todayLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ canLoadMoreReports: true })

        const first = page('p', MORE_REPORTS_PAGE_SIZE)
        listResponse = [200, { results: first, count: MORE_REPORTS_PAGE_SIZE + 5 }]
        await expectLogic(logic, () => {
            logic.actions.loadMoreReports()
        })
            .toDispatchActions(['loadMoreReportsSuccess'])
            .toMatchValues({ loadedMoreReports: first, canLoadMoreReports: true, moreReportsInInbox: 0 })
        expect(Object.fromEntries(listParams!.entries())).toEqual({
            limit: String(MORE_REPORTS_PAGE_SIZE),
            offset: '0',
            exclude: 'a',
            include_unowned: 'false',
        })

        const second = page('q', 3)
        listResponse = [200, { results: second, count: MORE_REPORTS_PAGE_SIZE + 5 }]
        await expectLogic(logic, () => {
            logic.actions.loadMoreReports()
        })
            .toDispatchActions(['loadMoreReportsSuccess'])
            .toMatchValues({
                loadedMoreReports: [...first, ...second],
                canLoadMoreReports: false,
                moreReportsInInbox: 2,
            })
        expect(listParams!.get('offset')).toBe(String(MORE_REPORTS_PAGE_SIZE))

        listResponse = [200, { results: [makeReport({ id: 'z' })], count: 5 }]
        await expectLogic(logic, () => {
            logic.actions.loadTopReports()
        })
            .toDispatchActions(['loadTopReportsSuccess'])
            .toMatchValues({ loadedMoreReports: [], canLoadMoreReports: true })

        await expectLogic(logic, () => {
            logic.actions.loadMoreReports()
        }).toDispatchActions(['loadMoreReportsSuccess'])
        expect(Object.fromEntries(listParams!.entries())).toMatchObject({ offset: '0', exclude: 'z' })
    })

    it('shows sample reports from ?sample=1 without asking the API, until ?sample=0 even if the reload fails', async () => {
        router.actions.push('/project/1/home', { sample: '1' })
        const logic = todayLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(listParams).toBeNull()
        expect(logic.values.reports.map((report) => isSampleReportId(report.id))).toEqual(
            Array(TOP_REPORT_COUNT).fill(true)
        )

        listResponse = [500, { detail: 'Error' }]
        router.actions.push('/project/1/home', { sample: '0' })
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ useSampleData: false, reports: [], reportsFailed: true })
        expect(listParams).not.toBeNull()
    })

    it.each([
        { status: 500, expected: { topReports: null, reportsFailed: true } },
        { status: 403, expected: { topReports: { results: [], count: 0 }, reportsFailed: false } },
    ])('keeps a failed load apart from an empty list, and treats $status that way', async ({ status, expected }) => {
        listResponse = [status, { detail: 'Error' }]
        const logic = todayLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues(expected)
    })

    it('leaves out the Explore products the person has no access to', () => {
        const appContext = window.POSTHOG_APP_CONTEXT!
        window.POSTHOG_APP_CONTEXT = {
            ...appContext,
            effective_resource_access_control: {
                ...appContext.effective_resource_access_control,
                [AccessControlResourceType.FeatureFlag]: AccessControlLevel.None,
            },
        }
        try {
            const logic = todayLogic()
            logic.mount()
            const products = logic.values.exploreItems.map((item) => item.product)
            expect(products).not.toContain('feature_flags')
            expect(products).toContain('product_analytics')
        } finally {
            window.POSTHOG_APP_CONTEXT = appContext
        }
    })
})
