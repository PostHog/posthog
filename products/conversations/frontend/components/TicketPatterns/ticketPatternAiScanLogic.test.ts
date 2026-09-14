import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { AiScanStatusApi } from '../../generated/api.schemas'
import { ticketPatternAiScanLogic } from './ticketPatternAiScanLogic'

const OFF: AiScanStatusApi = {
    enabled: false,
    scout_config_id: null,
    skill_name: null,
    last_run_at: null,
    ai_consent_granted: true,
}

const ON: AiScanStatusApi = {
    ...OFF,
    enabled: true,
    scout_config_id: 'cfg',
    skill_name: 'signals-scout-ticket-patterns',
}

describe('ticketPatternAiScanLogic', () => {
    let logic: ReturnType<typeof ticketPatternAiScanLogic.build>

    beforeEach(async () => {
        silenceKeaLoadersErrors()
        useMocks({
            get: { '/api/projects/:team_id/conversations/pattern_ai_scan/status/': () => [200, OFF] },
        })
        initKeaTests()
        logic = ticketPatternAiScanLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadStatusSuccess'])
    })

    afterEach(() => {
        logic?.unmount()
        resumeKeaLoadersErrors()
    })

    it('shows the scan as on straight from the enable response', async () => {
        useMocks({ post: { '/api/projects/:team_id/conversations/pattern_ai_scan/': () => [201, ON] } })

        logic.actions.enableScan()
        await expectLogic(logic).toMatchValues({ toggling: true })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.status).toEqual(ON)
        expect(logic.values.toggling).toEqual(false)
    })

    it('shows the scan as off straight from the disable response', async () => {
        logic.actions.loadStatusSuccess(ON)
        useMocks({
            get: { '/api/projects/:team_id/conversations/pattern_ai_scan/status/': () => [500, { detail: 'boom' }] },
            post: { '/api/projects/:team_id/conversations/pattern_ai_scan/disable/': () => [200, OFF] },
        })

        logic.actions.disableScan()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.status).toEqual(OFF)
        expect(logic.values.statusFailed).toEqual(false)
    })

    it('keeps a failed status load apart from a scan that was never turned on', async () => {
        useMocks({
            get: { '/api/projects/:team_id/conversations/pattern_ai_scan/status/': () => [500, { detail: 'boom' }] },
        })

        logic.actions.loadStatus()
        await expectLogic(logic).toDispatchActions(['loadStatusFailure'])

        expect(logic.values.statusFailed).toEqual(true)
    })

    it('keeps a failed reports load apart from a scan that found nothing', async () => {
        useMocks({
            get: { '/api/projects/:team_id/conversations/pattern_ai_scan/reports/': () => [500, { detail: 'boom' }] },
        })

        logic.actions.loadReports()
        await expectLogic(logic).toDispatchActions(['loadReportsFailure'])

        expect(logic.values.reports).toEqual([])
        expect(logic.values.reportsFailed).toEqual(true)

        useMocks({ get: { '/api/projects/:team_id/conversations/pattern_ai_scan/reports/': () => [200, []] } })
        logic.actions.loadReports()
        await expectLogic(logic).toDispatchActions(['loadReportsSuccess'])

        expect(logic.values.reportsFailed).toEqual(false)
    })

    it.each([
        {
            failure: 'the server refused and created nothing',
            code: 403,
            body: { detail: 'AI data processing is not approved for this organization.' },
            toasted: 'AI data processing is not approved for this organization.',
            statusAfter: OFF,
        },
        {
            failure: 'the scout was created and the answer was lost',
            code: 504,
            body: {},
            toasted: "Couldn't turn on the AI scan. Try again.",
            statusAfter: ON,
        },
    ])(
        'releases the switch and shows the state the server has when $failure',
        async ({ code, body, toasted, statusAfter }) => {
            const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'id')
            useMocks({
                get: { '/api/projects/:team_id/conversations/pattern_ai_scan/status/': () => [200, statusAfter] },
                post: { '/api/projects/:team_id/conversations/pattern_ai_scan/': () => [code, body] },
            })

            logic.actions.enableScan()
            await expectLogic(logic).toDispatchActions(['loadStatusSuccess'])

            expect(logic.values.status).toEqual(statusAfter)
            expect(logic.values.toggling).toEqual(false)
            expect(toast).toHaveBeenCalledWith(toasted)
        }
    )
})
