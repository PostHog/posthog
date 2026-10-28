import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeReport } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'
import { inboxTaskKickoffLogic } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import { SignalReport, SignalReportStatus } from 'products/signals/frontend/inbox/types'
import type { ReportPageApi } from 'products/today/frontend/generated/api.schemas'

import { todayReportLogic } from './todayReportLogic'
import { todayReportQueueLogic } from './todayReportQueueLogic'

const PAGE: ReportPageApi = {
    lead: 'Checkout fails for Safari users.',
    proposal: '',
    impact_sentence: '',
    named_pull_request: null,
    solution_names_pull_request: false,
    evidence: [],
    source_count: 0,
    impact_numbers: [],
    last_seen: null,
}

describe('todayReportLogic', () => {
    afterEach(() => {
        jest.restoreAllMocks()
    })

    test.each([
        [
            'a direct page load as a deep-link with its link source',
            '/project/997/home/reports/b?link_source=today',
            false,
            false,
            'b',
            1,
            [
                expect.objectContaining({
                    report_id: 'b',
                    surface: 'today',
                    open_method: 'deeplink',
                    link_source: 'today',
                    list: null,
                    rank: null,
                    list_size: null,
                }),
            ],
        ],
        [
            'a step onto the prefetched next report with its queue position',
            '/project/997/home/reports/a',
            true,
            true,
            'b',
            1,
            [
                expect.objectContaining({
                    report_id: 'b',
                    surface: 'today',
                    open_method: 'click',
                    source: 'step',
                    rank: 2,
                    list_size: 2,
                }),
            ],
        ],
        [
            'one open for each visit before the report loads',
            '/project/997/home/reports/b?link_source=today',
            false,
            false,
            'b',
            2,
            [
                expect.objectContaining({
                    report_id: 'b',
                    open_method: 'deeplink',
                    link_source: 'today',
                }),
                expect.objectContaining({
                    report_id: 'b',
                    open_method: 'deeplink',
                    link_source: null,
                }),
            ],
        ],
        ['no open for a sample report', '/project/997/home/reports/sample-pr', false, false, 'sample-pr', 1, []],
    ])('sends %s', async (_, path, step, prefetched, reportId, visits, opens) => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': {
                    results: [makeReport({ id: 'a' }), makeReport({ id: 'b' })],
                    count: 2,
                },
                '/api/projects/:team_id/signals/reports/:id/': ({ params }) => [
                    200,
                    makeReport({ id: params.id as string }),
                ],
                '/api/projects/:team_id/today/reports/:id/page/': () => [200, PAGE],
                '/api/projects/:team_id/today/briefing/': () => [404, {}],
            },
        })
        initKeaTests()
        const capture = jest.spyOn(posthog, 'capture')
        const sentOpens = (): unknown[] =>
            capture.mock.calls.filter(([event]) => event === 'Inbox report opened').map(([, props]) => props)
        const queueLogic = todayReportQueueLogic()
        queueLogic.mount()
        router.actions.push(path)
        await expectLogic(queueLogic).toFinishAllListeners()

        const logic = todayReportLogic({ reportId })
        logic.mount()
        if (prefetched) {
            await expectLogic(logic).toDispatchActions(['loadFullReportSuccess']).toFinishAllListeners()
        }
        // The report page prefetches its neighbors, and a prefetch is not a visit.
        expect(sentOpens()).toEqual([])
        if (step) {
            queueLogic.actions.openAdjacentReport(1)
        }
        for (let visit = 0; visit < visits; visit++) {
            logic.actions.reportVisited()
        }
        await expectLogic(logic)
            .toDispatchActions(prefetched ? [] : ['loadFullReportSuccess'])
            .toFinishAllListeners()

        expect(sentOpens()).toEqual(opens)
        // A copied address bar must not carry the link source to the next reader.
        expect(router.values.searchParams.link_source).toBeUndefined()
    })

    test.each([
        [
            'implements a report that is ready to act on',
            { actionability: 'immediately_actionable', status: SignalReportStatus.READY },
            ['createPrFromReport'] as const,
            'discussReport',
        ],
        [
            'investigates a report that needs a person',
            { actionability: 'requires_human_input', status: SignalReportStatus.PENDING_INPUT },
            ['openReportDiscussion', 'discussReport'] as const,
            'createPrFromReport',
        ],
    ])('starting with PostHog %s through a task linked to the report', async (_, overrides, kickoffs, other) => {
        const report = makeReport(overrides as Partial<SignalReport>)
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/:id/': () => [200, report],
                '/api/projects/:team_id/today/reports/:id/page/': () => [200, PAGE],
            },
        })
        initKeaTests()
        const kickoffLogic = inboxTaskKickoffLogic()
        kickoffLogic.mount()
        const logic = todayReportLogic({ reportId: report.id })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFullReportSuccess', 'loadPageSuccess'])

        await expectLogic(kickoffLogic, () => logic.actions.startWithPostHog())
            .toDispatchActions(
                kickoffs.map(
                    (kickoff) =>
                        (action: { type: string; payload: Record<string, any> }): boolean =>
                            action.type === kickoffLogic.actionTypes[kickoff] && action.payload.report.id === report.id
                )
            )
            .toNotHaveDispatchedActions([other])
    })

    test('asks Jev once per mark while a request is in flight and hides the marks when the flag turns off', async () => {
        const report = makeReport({ actionability: 'immediately_actionable', status: SignalReportStatus.READY })
        const calls = { keyClauses: 0, figureMarks: 0 }
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/:id/': () => [200, report],
                '/api/projects/:team_id/today/reports/:id/page/': () => [200, PAGE],
                '/api/projects/:team_id/today/reports/:id/figure_marks/': () => {
                    calls.figureMarks += 1
                    return [200, { marks: [] }]
                },
                '/api/projects/:team_id/today/reports/:id/key_clauses/': () => {
                    calls.keyClauses += 1
                    return [200, { lead: [], impact: [], proposal: [] }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        const logic = todayReportLogic({ reportId: report.id })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFullReportSuccess', 'loadPageSuccess'])

        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_REPORT_JEV], {
            [FEATURE_FLAGS.TODAY_REPORT_JEV]: true,
        })
        logic.actions.loadKeyClauses()
        logic.actions.loadFigureMarks()
        await expectLogic(logic).toFinishAllListeners()

        expect(calls).toEqual({ keyClauses: 1, figureMarks: 1 })
        expect(logic.values.shownKeyClauses).toEqual(logic.values.keyClauses)

        featureFlagLogic.actions.setFeatureFlags([], {})
        expect(logic.values.shownKeyClauses).toBeNull()
        expect(logic.values.shownFigureMarks).toBeNull()
    })
})
