import { initKeaTests } from '~/test/init'

import { experimentsFlagCleanupTaskRetrieve } from 'products/experiments/frontend/generated/api'

import { flagCleanupTaskLogic } from './flagCleanupTaskLogic'

jest.mock('products/experiments/frontend/generated/api', () => ({
    experimentsFlagCleanupTaskRetrieve: jest.fn(),
}))

const mockRetrieve = experimentsFlagCleanupTaskRetrieve as jest.Mock

describe('flagCleanupTaskLogic', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        mockRetrieve.mockReset()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('polls until the task run is terminal, then stops', async () => {
        mockRetrieve
            .mockResolvedValueOnce({
                task_id: 'a',
                run_status: 'in_progress',
                is_terminal: false,
                pr_url: null,
                error_message: null,
            })
            .mockResolvedValue({
                task_id: 'a',
                run_status: 'completed',
                is_terminal: true,
                pr_url: 'https://github.com/PostHog/posthog/pull/1',
                error_message: null,
            })

        const logic = flagCleanupTaskLogic({ experimentId: 1 })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)
        expect(mockRetrieve).toHaveBeenCalledTimes(1)

        await jest.advanceTimersByTimeAsync(30000)
        expect(mockRetrieve).toHaveBeenCalledTimes(2)
        expect(logic.values.cleanupTask?.pr_url).toBe('https://github.com/PostHog/posthog/pull/1')

        // Terminal — the interval is disposed, no further requests.
        await jest.advanceTimersByTimeAsync(120000)
        expect(mockRetrieve).toHaveBeenCalledTimes(2)
    })
})
