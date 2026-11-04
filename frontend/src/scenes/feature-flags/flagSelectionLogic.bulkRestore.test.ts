import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { BULK_RESTORE_REQUEST_TIMEOUT_MS, DeletedFlagInfo, flagSelectionLogic } from './flagSelectionLogic'

const deletedFlag = (id: number): DeletedFlagInfo => ({
    id,
    key: `flag-${id}`,
    rollout_state: 'partial',
    active_variant: null,
})

describe('flagSelectionLogic bulk restore', () => {
    let logic: ReturnType<typeof flagSelectionLogic.build>
    let restoreRequests: { id: number; body: Record<string, any> }[]

    function useRestoreMocks(
        restoreHandler: (id: number) => [number, any] | Promise<[number, any]> = () => [200, {}]
    ): void {
        restoreRequests = []
        useMocks({
            get: {
                '/api/projects/:team/feature_flags/': { count: 0, results: [] },
            },
            patch: {
                '/api/projects/:team/feature_flags/:id/': async ({ request, params }) => {
                    const id = Number(params.id)
                    restoreRequests.push({ id, body: (await request.json()) as Record<string, any> })
                    return restoreHandler(id)
                },
            },
        })
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => logic?.unmount())

    it('restores every flag the bulk delete removed, then reloads the list and closes the results', async () => {
        useRestoreMocks()
        logic = flagSelectionLogic()
        logic.mount()
        logic.actions.showResultsModal({ deleted: [deletedFlag(1), deletedFlag(2)], errors: [] })

        logic.actions.bulkRestoreFlags([deletedFlag(1), deletedFlag(2)])
        await expectLogic(logic).toDispatchActions(['bulkRestoreFlagsFinished', 'loadFeatureFlags', 'hideResultsModal'])

        expect(restoreRequests).toEqual([
            { id: 1, body: { deleted: false } },
            { id: 2, body: { deleted: false } },
        ])
        expect(logic.values.bulkRestoredIds).toEqual([1, 2])
        expect(logic.values.bulkRestoreFailures).toEqual([])
        expect(logic.values.bulkRestoreProgress).toEqual({ done: 2, total: 2 })
        expect(logic.values.bulkRestoreRunning).toBe(false)
        expect(logic.values.resultsModalVisible).toBe(false)
    })

    it('keeps restoring after a failure and leaves the results open to show it', async () => {
        useRestoreMocks((id) => {
            if (id === 2) {
                return [
                    400,
                    {
                        type: 'validation_error',
                        code: 'unsupported_config_version',
                        detail: 'These fields cannot be updated on this flag: deleted.',
                    },
                ]
            }
            return id === 4 ? [500, { detail: 'Server error' }] : [200, {}]
        })
        logic = flagSelectionLogic()
        logic.mount()
        const deleted = [deletedFlag(1), deletedFlag(2), deletedFlag(3), deletedFlag(4)]
        logic.actions.showResultsModal({ deleted, errors: [] })

        logic.actions.bulkRestoreFlags(deleted)
        await expectLogic(logic).toDispatchActions(['bulkRestoreFlagsFinished', 'loadFeatureFlags'])

        expect(restoreRequests.map(({ id }) => id)).toEqual([1, 2, 3, 4])
        // A version 2 flag can't be restored yet. The failure says so in the words the flag page uses.
        expect(logic.values.bulkRestoredIds).toEqual([1, 3])
        expect(logic.values.bulkRestoreFailures).toEqual([
            { id: 2, key: 'flag-2', errorMessage: 'Restoring is not available for this flag yet.', retryable: false },
            { id: 4, key: 'flag-4', errorMessage: 'Server error', retryable: true },
        ])
        expect(logic.values.resultsModalVisible).toBe(true)
    })

    it('leaves a flag the API refused out of the retry, and keeps its reason on show', async () => {
        let secondFlagFails = true
        useRestoreMocks((id) => {
            if (id === 1) {
                return [400, { type: 'validation_error', code: 'unsupported_config_version', detail: 'Not supported.' }]
            }
            return secondFlagFails ? [500, { detail: 'Server error' }] : [200, {}]
        })
        logic = flagSelectionLogic()
        logic.mount()
        logic.actions.showResultsModal({ deleted: [deletedFlag(1), deletedFlag(2)], errors: [] })

        logic.actions.bulkRestoreFlags(logic.values.restorableFlags)
        await expectLogic(logic).toDispatchActions(['bulkRestoreFlagsFinished'])
        // Trying flag 1 again would fail the same way, so the retry only offers flag 2.
        expect(logic.values.restorableFlags).toEqual([deletedFlag(2)])

        secondFlagFails = false
        logic.actions.bulkRestoreFlags(logic.values.restorableFlags)
        await expectLogic(logic).toDispatchActions(['bulkRestoreFlagsFinished'])

        expect(restoreRequests.map(({ id }) => id)).toEqual([1, 2, 2])
        expect(logic.values.bulkRestoreFailures).toEqual([
            { id: 1, key: 'flag-1', errorMessage: 'Restoring is not available for this flag yet.', retryable: false },
        ])
        expect(logic.values.stillDeletedFlags).toEqual([deletedFlag(1)])
        expect(logic.values.restorableFlags).toEqual([])
        // The retry had no failures of its own, but flag 1 is still deleted, so the results stay open.
        expect(logic.values.resultsModalVisible).toBe(true)
    })

    it('drops each flag from the still deleted list as soon as it is restored', async () => {
        let finishSecondRestore: () => void = () => {}
        const secondRestore = new Promise<void>((resolve) => {
            finishSecondRestore = resolve
        })
        useRestoreMocks(async (id) => {
            if (id === 2) {
                await secondRestore
            }
            return [200, {}]
        })
        logic = flagSelectionLogic()
        logic.mount()
        logic.actions.showResultsModal({ deleted: [deletedFlag(1), deletedFlag(2)], errors: [] })

        logic.actions.bulkRestoreFlags([deletedFlag(1), deletedFlag(2)])
        await expectLogic(logic).toDispatchActions([logic.actionCreators.bulkRestoreFlagSucceeded(1)])

        expect(logic.values.bulkRestoreRunning).toBe(true)
        expect(logic.values.stillDeletedFlags).toEqual([deletedFlag(2)])

        finishSecondRestore()
        await expectLogic(logic).toDispatchActions(['bulkRestoreFlagsFinished'])
        expect(logic.values.bulkRestoredIds).toEqual([1, 2])
    })

    it('retries only the flags a partly failed restore left deleted', async () => {
        let secondFlagFails = true
        useRestoreMocks((id) => (id === 2 && secondFlagFails ? [500, { detail: 'Server error' }] : [200, {}]))
        logic = flagSelectionLogic()
        logic.mount()
        logic.actions.showResultsModal({ deleted: [deletedFlag(1), deletedFlag(2)], errors: [] })

        logic.actions.bulkRestoreFlags(logic.values.stillDeletedFlags)
        await expectLogic(logic).toDispatchActions(['bulkRestoreFlagsFinished'])
        expect(logic.values.stillDeletedFlags).toEqual([deletedFlag(2)])
        expect(logic.values.bulkRestoreFailures).toEqual([
            { id: 2, key: 'flag-2', errorMessage: 'Server error', retryable: true },
        ])

        secondFlagFails = false
        logic.actions.bulkRestoreFlags(logic.values.stillDeletedFlags)
        await expectLogic(logic).toDispatchActions(['bulkRestoreFlagsFinished', 'hideResultsModal'])

        expect(restoreRequests.map(({ id }) => id)).toEqual([1, 2, 2])
        // The retry's success clears the first try's failure, and both restores still count.
        expect(logic.values.bulkRestoredIds).toEqual([1, 2])
        expect(logic.values.bulkRestoreFailures).toEqual([])
    })

    it('gives up on a restore that stalls, moves on, and leaves that flag to retry', async () => {
        // A request that never answers used to hold the loop, so the dialog stayed locked for good.
        useRestoreMocks((id) => (id === 1 ? new Promise<[number, any]>(() => {}) : [200, {}]))
        logic = flagSelectionLogic()
        logic.mount()
        logic.actions.showResultsModal({ deleted: [deletedFlag(1), deletedFlag(2)], errors: [] })

        jest.useFakeTimers()
        try {
            logic.actions.bulkRestoreFlags([deletedFlag(1), deletedFlag(2)])
            await jest.advanceTimersByTimeAsync(BULK_RESTORE_REQUEST_TIMEOUT_MS - 1)
            expect(logic.values.bulkRestoreRunning).toBe(true)
            await jest.advanceTimersByTimeAsync(1)
        } finally {
            jest.useRealTimers()
        }
        await expectLogic(logic).toDispatchActions(['bulkRestoreFlagsFinished'])

        expect(restoreRequests.map(({ id }) => id)).toEqual([1, 2])
        expect(logic.values.bulkRestoreRunning).toBe(false)
        expect(logic.values.bulkRestoreFailures).toEqual([
            { id: 1, key: 'flag-1', errorMessage: 'The request timed out. Try again.', retryable: true },
        ])
        expect(logic.values.stillDeletedFlags).toEqual([deletedFlag(1)])
        expect(logic.values.resultsModalVisible).toBe(true)
    })

    it('starts each bulk delete result without the last restore', async () => {
        useRestoreMocks()
        logic = flagSelectionLogic()
        logic.mount()
        logic.actions.showResultsModal({ deleted: [deletedFlag(1)], errors: [] })
        logic.actions.bulkRestoreFlags([deletedFlag(1)])
        await expectLogic(logic).toDispatchActions(['bulkRestoreFlagsFinished'])

        logic.actions.showResultsModal({ deleted: [deletedFlag(4)], errors: [] })

        expect(logic.values.bulkRestoreFailures).toEqual([])
        expect(logic.values.bulkRestoredIds).toEqual([])
        expect(logic.values.stillDeletedFlags).toEqual([deletedFlag(4)])
    })
})
