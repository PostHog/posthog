import { expectLogic } from 'kea-test-utils'

import { dispatchChangeRequestCreated } from 'scenes/approvals/utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { BULK_ARCHIVE_MAX_FLAGS, flagSelectionLogic } from './flagSelectionLogic'

jest.mock('scenes/approvals/utils', () => ({
    ...jest.requireActual('scenes/approvals/utils'),
    dispatchChangeRequestCreated: jest.fn(),
}))

describe('flagSelectionLogic bulk archive', () => {
    let logic: ReturnType<typeof flagSelectionLogic.build>
    let archiveRequests: { id: number; body: Record<string, any> }[]

    function useArchiveMocks(archiveHandler: (id: number) => [number, any] = () => [200, {}]): void {
        archiveRequests = []
        useMocks({
            get: {
                '/api/projects/:team/feature_flags/': { count: 0, results: [] },
            },
            patch: {
                '/api/projects/:team/feature_flags/:id/': async ({ request, params }) => {
                    const id = Number(params.id)
                    archiveRequests.push({ id, body: (await request.json()) as Record<string, any> })
                    return archiveHandler(id)
                },
            },
        })
    }

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    afterEach(() => logic?.unmount())

    it('disables every selected flag as it archives it, then reloads the list', async () => {
        useArchiveMocks()
        logic = flagSelectionLogic()
        logic.mount()

        logic.actions.bulkArchiveFlags([1, 2])
        await expectLogic(logic).toDispatchActions(['bulkArchiveFlagsFinished', 'loadFeatureFlags'])

        // `active: false` matters: the API rejects an archived flag that is still enabled
        expect(archiveRequests).toEqual([
            { id: 1, body: { archived: true, active: false } },
            { id: 2, body: { archived: true, active: false } },
        ])
        expect(logic.values.bulkArchiveResult).toEqual({ archivedIds: [1, 2], failed: [] })
        expect(logic.values.bulkArchiveProgress).toEqual({ done: 2, total: 2 })
        expect(logic.values.bulkArchiveRunning).toBe(false)
    })

    it('keeps archiving the remaining flags when one needs approval and another fails', async () => {
        useArchiveMocks((id) => {
            if (id === 1) {
                return [409, { change_request_id: 'cr-1' }]
            }
            if (id === 2) {
                return [500, { detail: 'Server error' }]
            }
            return [200, {}]
        })
        logic = flagSelectionLogic()
        logic.mount()

        logic.actions.bulkArchiveFlags([1, 2, 3])
        await expectLogic(logic).toFinishAllListeners()

        expect(archiveRequests.map(({ id }) => id)).toEqual([1, 2, 3])
        expect(logic.values.bulkArchiveResult?.archivedIds).toEqual([3])
        expect(logic.values.bulkArchiveResult?.failed).toEqual([
            { id: 1, errorMessage: expect.any(String), approvalPending: true },
            { id: 2, errorMessage: 'Server error', approvalPending: false },
        ])
        // Only the approval-pending flag announces a change request; the 500 failure must not
        expect(dispatchChangeRequestCreated).toHaveBeenCalledTimes(1)
        expect(dispatchChangeRequestCreated).toHaveBeenCalledWith({ resourceType: 'feature_flag', resourceId: 1 })
        // Failed flags still advance the progress counter, and the run ends
        expect(logic.values.bulkArchiveProgress).toEqual({ done: 3, total: 3 })
        expect(logic.values.bulkArchiveRunning).toBe(false)
    })

    it.each([
        ['an empty selection', []],
        ['a selection above the cap', Array.from({ length: BULK_ARCHIVE_MAX_FLAGS + 1 }, (_, i) => i + 1)],
    ])('refuses to run for %s without issuing any archive requests', async (_label, ids) => {
        useArchiveMocks()
        logic = flagSelectionLogic()
        logic.mount()

        logic.actions.bulkArchiveFlags(ids)
        await expectLogic(logic).toFinishAllListeners()

        expect(archiveRequests).toHaveLength(0)
        expect(logic.values.bulkArchiveResult).toBeNull()
        expect(logic.values.bulkArchiveRunning).toBe(false)
    })
})
