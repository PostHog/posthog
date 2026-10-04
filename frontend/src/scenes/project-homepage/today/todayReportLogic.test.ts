import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeReport } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'
import { inboxTaskKickoffLogic } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import { SignalReport, SignalReportStatus } from 'products/signals/frontend/inbox/types'
import type { KeyClausesRequestApi, ReportPageApi } from 'products/today/frontend/generated/api.schemas'

import { todayReportLogic } from './todayReportLogic'

const PAGE: ReportPageApi = {
    lead: 'Checkout fails for Safari users.',
    proposal: '',
    impact_sentence: '',
    named_pull_request: null,
    solution_names_pull_request: false,
    signals: [],
    evidence_signal_ids: [],
    source_count: 0,
    impact_numbers: [],
    last_seen: null,
}

describe('todayReportLogic', () => {
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
            },
            post: {
                '/api/projects/:team_id/today/reports/:id/key_clauses/': async ({ request }) => {
                    calls.keyClauses += 1
                    const { requests } = (await request.json()) as KeyClausesRequestApi
                    return [200, { texts: requests.map(({ text }) => ({ text, key_clauses: [] })) }]
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
        expect(logic.values.shownKeyClauses).toEqual({})
        expect(logic.values.shownFigureMarks).toBeNull()
    })
})
