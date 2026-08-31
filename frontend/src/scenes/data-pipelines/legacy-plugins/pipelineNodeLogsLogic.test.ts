import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
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

    it('surfaces a toast when the initial log fetch fails', async () => {
        jest.spyOn(api.batchExports, 'logs').mockRejectedValue(new Error('Non-OK response'))
        await expectLogic(teamLogic).toFinishAllListeners()

        logic = pipelineNodeLogsLogic({ id: BATCH_EXPORT_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadLogs', 'loadLogsFailure'])

        expect(lemonToast.error).toHaveBeenCalledWith('Failed to load logs: Non-OK response')
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
