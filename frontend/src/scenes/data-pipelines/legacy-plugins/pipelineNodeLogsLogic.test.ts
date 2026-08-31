import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { pipelineNodeLogsLogic } from './pipelineNodeLogsLogic'

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    lemonToast: {
        error: jest.fn(),
    },
}))

const BATCH_EXPORT_ID = 'test-export-id'

describe('pipelineNodeLogsLogic', () => {
    let logic: ReturnType<typeof pipelineNodeLogsLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('surfaces a toast when a status-less network failure would otherwise go unreported', async () => {
        jest.spyOn(api.batchExports, 'logs').mockRejectedValue(new Error('Non-OK response'))
        await expectLogic(teamLogic).toFinishAllListeners()

        logic = pipelineNodeLogsLogic({ id: BATCH_EXPORT_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadLogs', 'loadLogsFailure'])

        expect(lemonToast.error).toHaveBeenCalledWith('Failed to load logs: Non-OK response')
        expect(logic.values.logs).toEqual([])
    })

    it('stays silent on an HTTP failure so the loaders onFailure toast is not duplicated', async () => {
        jest.spyOn(api.batchExports, 'logs').mockRejectedValue(new ApiError('Server error', 500))
        await expectLogic(teamLogic).toFinishAllListeners()

        logic = pipelineNodeLogsLogic({ id: BATCH_EXPORT_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadLogs', 'loadLogsFailure'])

        // A failure with an HTTP status is toasted by initKea's onFailure, so this viewer adds none.
        expect(lemonToast.error).not.toHaveBeenCalled()
        expect(logic.values.logs).toEqual([])
    })

    it('swallows background poll failures without a toast', async () => {
        jest.spyOn(api.batchExports, 'logs')
            .mockResolvedValueOnce({ results: [] } as any)
            .mockRejectedValue(new Error('Non-OK response'))
        await expectLogic(teamLogic).toFinishAllListeners()

        logic = pipelineNodeLogsLogic({ id: BATCH_EXPORT_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadLogsSuccess'])

        logic.actions.pollBackgroundLogs()
        await expectLogic(logic).toDispatchActions(['pollBackgroundLogsSuccess'])

        expect(lemonToast.error).not.toHaveBeenCalled()
        expect(logic.values.backgroundLogs).toEqual([])
    })
})
