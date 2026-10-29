import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DeletedFlagInfo, flagSelectionLogic } from './flagSelectionLogic'

const deletedFlag = (id: number): DeletedFlagInfo => ({
    id,
    key: `flag-${id}`,
    rollout_state: 'partial',
    active_variant: null,
})

describe('flagSelectionLogic bulk restore', () => {
    let logic: ReturnType<typeof flagSelectionLogic.build>
    let restoreRequests: { id: number; body: Record<string, any> }[]

    function useRestoreMocks(restoreHandler: (id: number) => [number, any] = () => [200, {}]): void {
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
        expect(logic.values.bulkRestoreResult).toEqual({ restoredIds: [1, 2], failed: [] })
        expect(logic.values.bulkRestoreProgress).toEqual({ done: 2, total: 2 })
        expect(logic.values.bulkRestoreRunning).toBe(false)
        expect(logic.values.resultsModalVisible).toBe(false)
    })

    it('keeps restoring after a failure and leaves the results open to show it', async () => {
        useRestoreMocks((id) =>
            id === 2
                ? [
                      400,
                      {
                          type: 'validation_error',
                          code: 'unsupported_config_version',
                          detail: 'These fields cannot be updated on this flag: deleted.',
                      },
                  ]
                : [200, {}]
        )
        logic = flagSelectionLogic()
        logic.mount()
        const deleted = [deletedFlag(1), deletedFlag(2), deletedFlag(3)]
        logic.actions.showResultsModal({ deleted, errors: [] })

        logic.actions.bulkRestoreFlags(deleted)
        await expectLogic(logic).toDispatchActions(['bulkRestoreFlagsFinished', 'loadFeatureFlags'])

        expect(restoreRequests.map(({ id }) => id)).toEqual([1, 2, 3])
        // A version 2 flag can't be restored yet. The failure says so in the words the flag page uses.
        expect(logic.values.bulkRestoreResult).toEqual({
            restoredIds: [1, 3],
            failed: [{ id: 2, key: 'flag-2', errorMessage: 'Restoring is not available for this flag yet.' }],
        })
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

        expect(logic.values.bulkRestoreResult).toBeNull()
    })
})
