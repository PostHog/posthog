import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { notebookKernelInfoLogic } from './notebookKernelInfoLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        notebooks: {
            kernelStatus: jest.fn().mockResolvedValue({ backend: null, status: 'stopped' }),
            kernelExecute: jest.fn(),
            kernelStart: jest.fn(),
            kernelStop: jest.fn(),
            kernelRestart: jest.fn(),
            kernelConfig: jest.fn(),
        },
    },
}))

describe('notebookKernelInfoLogic', () => {
    const mockedKernelStatus = api.notebooks.kernelStatus as jest.Mock

    beforeEach(() => {
        jest.clearAllMocks()
        jest.useFakeTimers()
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('polls kernel status on mount in notebook mode', async () => {
        const logic = notebookKernelInfoLogic({ shortId: 'abc123', mode: 'notebook' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadKernelInfo'])
        expect(mockedKernelStatus).toHaveBeenCalledWith('abc123')
        logic.unmount()
    })

    it('does not call kernel status in canvas mode', async () => {
        const logic = notebookKernelInfoLogic({ shortId: 'canvas-key-tab', mode: 'canvas' })
        logic.mount()
        // Advance well past the 10s poll interval to confirm no scheduled refresh fires.
        jest.advanceTimersByTime(30_000)
        expect(mockedKernelStatus).not.toHaveBeenCalled()
        logic.unmount()
    })

    it('defaults to polling when mode is undefined (backwards compat)', async () => {
        const logic = notebookKernelInfoLogic({ shortId: 'def456' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadKernelInfo'])
        expect(mockedKernelStatus).toHaveBeenCalledWith('def456')
        logic.unmount()
    })
})
