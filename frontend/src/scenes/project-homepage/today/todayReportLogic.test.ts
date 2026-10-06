import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeReport } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'
import { inboxTaskKickoffLogic } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import { SignalReport, SignalReportStatus } from 'products/signals/frontend/inbox/types'
import type { ReportPageApi } from 'products/today/frontend/generated/api.schemas'

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
            ['createPrFromReport'],
            'discussReport',
        ],
        [
            'investigates a report that needs a person',
            { actionability: 'requires_human_input', status: SignalReportStatus.PENDING_INPUT },
            ['openReportDiscussion', 'discussReport'],
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
            .toDispatchActions(kickoffs)
            .toNotHaveDispatchedActions([other])
    })
})
