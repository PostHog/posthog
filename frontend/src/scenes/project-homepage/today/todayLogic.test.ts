import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeReport } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'
import { SignalReport } from 'products/signals/frontend/inbox/types'
import type { BriefingApi, BriefingItemReportApi } from 'products/today/frontend/generated/api.schemas'

import { BRIEFING_POLL_MS, TOP_REPORT_COUNT, reportIdFromPath, todayLogic } from './todayLogic'
import { isSampleReportId } from './todaySampleReports'
import { GENERAL_REPORT_PROMPTS, briefingForReports, reportPrompts } from './todaySignalReports'

function makeBriefing(overrides: Partial<BriefingApi> = {}): BriefingApi {
    return {
        id: 'briefing-1',
        local_day: '2026-09-30',
        headline: 'One report needs your input',
        paragraphs: [[{ text: 'Signup form rejects emails', item_key: 'report:a', highlight: true }]],
        items: [
            {
                key: 'report:a',
                title: 'Signup form rejects emails',
                label: 'Signup form rejects emails',
                signal: 'P1, waits for you',
                url: '/project/1/inbox/reports/a',
                rank: 1,
                group: 'report',
                source: 'self_driving',
                reason: 'waiting_for_you',
                state: 'open',
                source_product: null,
                report: null,
            },
        ],
        more_reports_count: 0,
        open_reports_count: 0,
        status: 'ready',
        writer: 'agent',
        created_at: '2026-09-30T06:00:00Z',
        ready_at: '2026-09-30T06:00:20Z',
        ...overrides,
    }
}

describe('todayLogic', () => {
    let listResponse: [number, any]
    let listParams: URLSearchParams | null
    let briefingResponses: [number, any][]
    let briefingCalls: number

    beforeEach(() => {
        listResponse = [200, { results: [], count: 0 }]
        listParams = null
        briefingResponses = [[404, { detail: 'Not found.' }]]
        briefingCalls = 0
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/for_you/': ({ request }) => {
                    listParams = new URL(request.url).searchParams
                    return listResponse
                },
                '/api/projects/:team_id/today/briefing/': () => {
                    briefingCalls += 1
                    return briefingResponses.length > 1 ? briefingResponses.shift()! : briefingResponses[0]
                },
            },
            post: {
                '/api/projects/:team_id/today/briefing/refresh/': () => [
                    200,
                    makeBriefing({ id: 'b-next', status: 'writing' }),
                ],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('falls back to the report list when there is no personal briefing', async () => {
        const reports = [makeReport({ id: 'a' })]
        listResponse = [200, { results: reports, count: 1 }]
        const logic = todayLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            reports,
            personalBriefingFailed: true,
            briefingWaiting: false,
            showPersonalBriefing: false,
            briefingItems: [],
        })
    })

    it.each([
        {
            shown: 'the briefing',
            hasBriefing: true,
            expected: ['briefing id: `briefing-1`', '](http://localhost/project/997/home/reports/a)', 'report id `a`'],
        },
        {
            shown: 'the report list',
            hasBriefing: false,
            expected: [
                'briefing is not written yet',
                '](http://localhost/project/997/home/reports/r-1)',
                'report id `r-1`',
            ],
        },
    ])('sends PostHog AI the question with $shown as context', async ({ hasBriefing, expected }) => {
        listResponse = [200, { results: [makeReport({ id: 'r-1' })], count: 1 }]
        if (hasBriefing) {
            briefingResponses = [[200, makeBriefing()]]
        }
        const logic = todayLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.askAi('Why is signup broken?', 'ask_box')

        const prompt = router.values.searchParams.ask as string
        expect(prompt.startsWith('Why is signup broken?\n')).toBe(true)
        for (const text of expected) {
            expect(prompt.toLowerCase()).toContain(text.toLowerCase())
        }
    })

    it('keeps the last briefing on screen, polls while the next is written, and stops when it is ready', async () => {
        jest.useFakeTimers()
        const previous = makeBriefing({ id: 'b-previous', status: 'writing' })
        const ready = makeBriefing()
        briefingResponses = [
            [200, previous],
            [200, ready],
        ]
        const logic = todayLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadPersonalBriefingSuccess']).toMatchValues({
            showPersonalBriefing: true,
            briefingWaiting: true,
            personalBriefing: previous,
        })

        await expectLogic(logic, () => {
            jest.advanceTimersByTime(BRIEFING_POLL_MS)
        })
            .toDispatchActions(['pollBriefing', 'loadPersonalBriefingSuccess'])
            .toMatchValues({ briefingWaiting: false, personalBriefing: ready })

        await jest.advanceTimersByTimeAsync(BRIEFING_POLL_MS * 3)
        expect(briefingCalls).toBe(2)
    })

    it('keeps waiting from the refresh click until the reloaded briefing says it is written', async () => {
        const shown = makeBriefing()
        briefingResponses = [
            [200, shown],
            [200, { ...shown, status: 'writing' }],
        ]
        const logic = todayLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPersonalBriefingSuccess']).toMatchValues({
            briefingWaiting: false,
        })

        await expectLogic(logic, () => {
            logic.actions.refreshBriefing()
        })
            .toDispatchActions(['refreshBriefing', 'refreshBriefingSuccess'])
            .toMatchValues({ briefingWaiting: true })
            .toDispatchActions(['loadPersonalBriefing', 'loadPersonalBriefingSuccess'])
            .toMatchValues({ briefingWaiting: true })
    })

    it.each([
        ['crosses 8:00', new Date(2026, 8, 30, 7, 59, 45), null],
        ['sleeps from one afternoon to the next', new Date(2026, 8, 30, 14, 0, 0), new Date(2026, 9, 1, 14, 0, 0)],
    ])('reloads the briefing when an open tab %s', async (_name, start, wakeAt) => {
        jest.useFakeTimers()
        jest.setSystemTime(start)
        briefingResponses = [[200, makeBriefing()]]
        const logic = todayLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPersonalBriefingSuccess'])

        await expectLogic(logic, () => {
            if (wakeAt) {
                jest.setSystemTime(wakeAt)
            }
            jest.advanceTimersByTime(30_000)
        }).toDispatchActions(['tick', 'loadPersonalBriefing', 'loadPersonalBriefingSuccess'])
        expect(briefingCalls).toBe(2)

        await jest.advanceTimersByTimeAsync(30_000)
        expect(briefingCalls).toBe(2)
    })

    test.each([
        ['nothing is off the list yet', ['open', 'open'], null],
        ['a resolved and a dismissed item both count', ['done', 'dismissed', 'open'], { done: 2, total: 3 }],
    ] as const)('counts briefing progress when %s', async (_name, states, expected) => {
        const [item] = makeBriefing().items
        briefingResponses = [
            [200, makeBriefing({ items: states.map((state, index) => ({ ...item, key: `report:${index}`, state })) })],
        ]
        const logic = todayLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadPersonalBriefingSuccess'])
            .toMatchValues({ briefingProgress: expected })
    })

    it('gives a hover card to the reports of both lists, and only to items with report details', async () => {
        const [item] = makeBriefing().items
        const report: BriefingItemReportApi = {
            priority: 'P1',
            summary: 'Signups fail for plus-addressed emails.',
            pull_request_state: null,
            pull_request_url: null,
            signal_count: 3,
            updated_at: '2026-09-30T08:00:00Z',
            metrics: [],
            charts: [],
        }
        listResponse = [200, { results: [makeReport({ id: 'team-a' })], count: 1 }]
        briefingResponses = [
            [
                200,
                makeBriefing({
                    items: [
                        { ...item, report },
                        // A deleted report, and an item from an older briefing that is not a report.
                        { ...item, key: 'report:deleted', state: 'dismissed' },
                        { ...item, key: 'dashboard:12', group: 'dashboard', reason: 'dashboard_you_viewed' },
                    ],
                }),
            ],
        ]
        const logic = todayLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadPersonalBriefingSuccess'])
        expect(Object.keys(logic.values.reportPreviews.briefing)).toEqual(['report:a'])
        expect(Object.keys(logic.values.reportPreviews.sidebar)).toEqual(['report:a'])
        expect(Object.keys(logic.values.teamReportPreviews.briefing)).toEqual(['team-a'])
        expect(Object.keys(logic.values.teamReportPreviews.sidebar)).toEqual(['team-a'])
    })

    it('asks for the top reports for the person and counts the rest', async () => {
        const reports = [makeReport({ id: 'a' }), makeReport({ id: 'b' })]
        listResponse = [200, { results: reports, count: 9 }]
        const logic = todayLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ reports, moreReportCount: 7 })
        expect(Object.fromEntries(listParams!.entries())).toEqual({ limit: String(TOP_REPORT_COUNT) })
    })

    it('shows sample reports from ?sample=1 without asking the API, until ?sample=0', async () => {
        router.actions.push('/project/1/home', { sample: '1' })
        const logic = todayLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(listParams).toBeNull()
        expect(logic.values.reports.map((report) => isSampleReportId(report.id))).toEqual(
            Array(TOP_REPORT_COUNT).fill(true)
        )

        router.actions.push('/project/1/home', { sample: '0' })
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ useSampleData: false, reports: [] })
        expect(listParams).not.toBeNull()
    })

    it('keeps a failed load apart from an empty list', async () => {
        listResponse = [500, { detail: 'Server error' }]
        const logic = todayLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ topReports: null, reportsFailed: true })
    })

    test.each([
        ['/project/1/home/reports/abc', 'abc'],
        ['/home/reports/abc/', 'abc'],
        ['/project/1/home', null],
        ['/project/1/home/reports/abc/signals', null],
        ['/project/1/inbox/reports/abc', null],
    ])('reads the report id from %s', (pathname, reportId) => {
        expect(reportIdFromPath(pathname)).toBe(reportId)
    })

    it('links every report from the briefing and keeps acronyms in titles', () => {
        const briefing = briefingForReports([
            makeReport({
                id: 'a',
                title: 'Signup form rejects emails',
                implementation_pr_url: 'https://example.com/1',
            }),
            makeReport({ id: 'b', title: 'Pricing page drops off' }),
            makeReport({ id: 'c', title: 'LLM costs doubled' }),
        ])

        expect(briefing.flat().filter((segment) => segment.reportId)).toEqual([
            { text: 'Signup form rejects emails', reportId: 'a', highlight: true },
            { text: 'pricing page drops off', reportId: 'b' },
            { text: 'LLM costs doubled', reportId: 'c' },
        ])
    })

    test.each([
        ['an action-capable report', {}, ['Draft the fix']],
        ['a report with a pull request', { implementation_pr_url: 'https://example.com/1' }, GENERAL_REPORT_PROMPTS],
        ['a report judged not actionable', { actionability: 'not_actionable' }, GENERAL_REPORT_PROMPTS],
    ])('offers the right prompts for %s', (_, overrides, expected) => {
        const report = makeReport({ suggested_prompts: ['Draft the fix'], ...(overrides as Partial<SignalReport>) })
        expect(reportPrompts(report)).toEqual(expected)
    })
})
