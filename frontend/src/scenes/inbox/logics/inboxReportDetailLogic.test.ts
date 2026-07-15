import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { signalsReportArtefactsDiff, signalsReportsSignalsRetrieve } from 'products/signals/frontend/generated/api'

import { inboxReportDetailLogic } from './inboxReportDetailLogic'

// The report detail logic pulls the branch diff, the linked signals, and the reviewer picker from the
// generated signals client on mount. Stub the generated module so mounting doesn't hit the network; the
// diff function is re-stubbed per test to drive the failure paths.
jest.mock('products/signals/frontend/generated/api', () => ({
    signalsReportsSignalsRetrieve: jest.fn(),
    signalsReportArtefactsDiff: jest.fn(),
}))

const signalsRetrieveMock = signalsReportsSignalsRetrieve as jest.Mock
const diffMock = signalsReportArtefactsDiff as jest.Mock

describe('inboxReportDetailLogic', () => {
    let logic: ReturnType<typeof inboxReportDetailLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.signalReports, 'artefacts').mockResolvedValue({ results: [], next: null } as any)
        jest.spyOn(api.signalReports, 'availableReviewers').mockResolvedValue([] as any)
        signalsRetrieveMock.mockResolvedValue({ signals: [] })
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    function mountLogic(): void {
        logic = inboxReportDetailLogic({ reportId: 'report-1' })
        logic.mount()
    }

    it('degrades the diff to a quiet inline message when no GitHub integration can access the repo (404)', async () => {
        // The backend returns this exact 404 body when the report's commit lives in a repo the team's
        // GitHub installation can't reach.
        const message = "No GitHub integration can access 'PostHog/wizard'."
        diffMock.mockRejectedValue(new ApiError(message, 404, undefined, { error: message }))

        mountLogic()

        // The loader swallows the expected 404 and resolves with null, so nothing bubbles up as a
        // captured frontend exception (no `loadReportDiffFailure`).
        await expectLogic(logic, () => {
            logic.actions.loadReportDiff({ artefactId: 'commit-1' })
        })
            .toDispatchActions(['loadReportDiff', 'setReportDiffUnavailable', 'loadReportDiffSuccess'])
            .toNotHaveDispatchedActions(['loadReportDiffFailure'])
            .toMatchValues({ reportDiff: null, reportDiffError: message })
    })

    it('rethrows an unexpected diff failure instead of silently degrading (500)', async () => {
        diffMock.mockRejectedValue(new ApiError('Server error', 500))

        mountLogic()

        await expectLogic(logic, () => {
            logic.actions.loadReportDiff({ artefactId: 'commit-1' })
        })
            .toDispatchActions(['loadReportDiff', 'loadReportDiffFailure'])
            .toNotHaveDispatchedActions(['setReportDiffUnavailable'])
        expect(logic.values.reportDiffError).toContain("Couldn't load the diff")
    })
})
