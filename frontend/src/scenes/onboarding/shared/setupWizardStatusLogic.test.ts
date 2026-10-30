import { expectLogic } from 'kea-test-utils'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { initKeaTests } from '~/test/init'

import { tasksList } from 'products/tasks/frontend/generated/api'

import { setupWizardStatusLogic } from './setupWizardStatusLogic'

jest.mock('products/tasks/frontend/generated/api', () => ({
    tasksList: jest.fn(),
    tasksRunsList: jest.fn(),
}))

describe('setupWizardStatusLogic', () => {
    beforeEach(async () => {
        initKeaTests()
        await expectLogic(preflightLogic).toFinishAllListeners()
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.resetAllMocks()
    })

    it.each(['completed', 'failed'] as const)('refreshes an installing run until it is %s', async (status) => {
        const mockTasksList = tasksList as jest.Mock
        const task = {
            id: 'example-task',
            created_at: '2026-09-23T10:00:00Z',
            latest_run: { id: 'example-run', status: 'in_progress', output: null },
        }
        mockTasksList.mockResolvedValueOnce({ results: [task] })
        const logic = setupWizardStatusLogic()
        logic.mount()
        try {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.setupStatus).toEqual({ kind: 'installing' })

            const output = status === 'completed' ? { pr_url: 'https://github.com/example/project/pull/12' } : null
            mockTasksList.mockResolvedValue({
                results: [{ ...task, latest_run: { ...task.latest_run, status, output } }],
            })
            jest.advanceTimersByTime(10_000)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.setupStatus).toEqual(
                output ? { kind: 'pull_request', pullRequest: { url: output.pr_url, merged: false } } : null
            )

            if (output) {
                mockTasksList.mockResolvedValue({
                    results: [{ ...task, latest_run: { status, output: { ...output, pr_merged: true } } }],
                })
                jest.advanceTimersByTime(10_000)
                await expectLogic(logic).toFinishAllListeners()
                expect(logic.values.setupStatus).toEqual({
                    kind: 'pull_request',
                    pullRequest: { url: output.pr_url, merged: true },
                })
            }
            const requests = mockTasksList.mock.calls.length
            jest.advanceTimersByTime(20_000)
            await expectLogic(logic).toFinishAllListeners()
            expect(mockTasksList).toHaveBeenCalledTimes(requests)
        } finally {
            logic.unmount()
        }
    })
})
