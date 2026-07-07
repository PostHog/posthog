import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { BULK_COPY_MAX_FLAGS, flagSelectionLogic } from './flagSelectionLogic'

const TARGET_A = 500
const TARGET_B = 501

describe('flagSelectionLogic bulk copy', () => {
    let logic: ReturnType<typeof flagSelectionLogic.build>
    let copyRequests: Record<string, any>[]

    function useCopyMocks(
        copyHandler: (body: Record<string, any>) => [number, any],
        bulkKeys: Record<string, string> = {}
    ): void {
        copyRequests = []
        useMocks({
            get: {
                '/api/projects/:team/feature_flags/': { count: 0, results: [] },
            },
            post: {
                '/api/projects/:team/feature_flags/bulk_keys/': [200, { keys: bulkKeys }],
                '/api/organizations/:org/feature_flags/copy_flags/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    copyRequests.push(body)
                    return copyHandler(body)
                },
            },
        })
    }

    function successResponse(key: string, extra: Record<string, any> = {}): [number, any] {
        return [200, { success: [{ id: 1, key, name: key, active: true, ...extra }], failed: [] }]
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => logic?.unmount())

    it('resolves flag IDs to keys and issues one copy request per key with the configured payload', async () => {
        useCopyMocks((body) => successResponse(body.feature_flag_key), { '1': 'flag-a', '2': 'flag-b' })
        logic = flagSelectionLogic()
        logic.mount()

        logic.actions.openBulkCopyModal({ sourceProjectId: MOCK_TEAM_ID, flagIds: [1, 2, 3] })
        logic.actions.setBulkCopyTargetProjectIds([TARGET_A, TARGET_B])
        logic.actions.setBulkCopySchedule(true)
        logic.actions.bulkCopyFlags()
        await expectLogic(logic).toFinishAllListeners()

        expect(copyRequests).toEqual([
            {
                feature_flag_key: 'flag-a',
                from_project: MOCK_TEAM_ID,
                target_project_ids: [TARGET_A, TARGET_B],
                copy_schedule: true,
                disable_copied_flag: false,
            },
            {
                feature_flag_key: 'flag-b',
                from_project: MOCK_TEAM_ID,
                target_project_ids: [TARGET_A, TARGET_B],
                copy_schedule: true,
                disable_copied_flag: false,
            },
        ])
        expect(logic.values.bulkCopyResult).toEqual({
            copied: [
                { key: 'flag-a', projectIds: [TARGET_A, TARGET_B] },
                { key: 'flag-b', projectIds: [TARGET_A, TARGET_B] },
            ],
            failed: [],
            warnings: [],
            // ID 3 didn't resolve to a key (e.g. deleted since selection)
            skippedFlagCount: 1,
        })
        expect(logic.values.bulkCopyRunning).toBe(false)
        expect(logic.values.bulkCopyProgress).toEqual({ done: 2, total: 2 })
    })

    it('aggregates per-project failures, approval-pending entries, and warnings without blocking other targets', async () => {
        useCopyMocks((body) => {
            if (body.feature_flag_key === 'flag-a') {
                return [
                    200,
                    {
                        success: [
                            { id: 1, key: 'flag-a', name: '', active: false, flag_dependency_warnings: ['dropped'] },
                        ],
                        failed: [
                            {
                                project_id: TARGET_B,
                                error_message: 'Approval required',
                                approval_pending: true,
                                change_request_id: 'cr-1',
                            },
                        ],
                    },
                ]
            }
            return [
                200,
                {
                    success: [{ id: 2, key: 'flag-b', name: '', active: true, schedule_copy_warning: 'no schedules' }],
                    failed: [{ project_id: TARGET_A, error_message: 'Project not found.' }],
                },
            ]
        })
        logic = flagSelectionLogic()
        logic.mount()

        logic.actions.openBulkCopyModal({ sourceProjectId: MOCK_TEAM_ID, flagKeys: ['flag-a', 'flag-b'] })
        logic.actions.setBulkCopyTargetProjectIds([TARGET_A, TARGET_B])
        logic.actions.bulkCopyFlags()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.bulkCopyResult).toEqual({
            copied: [
                { key: 'flag-a', projectIds: [TARGET_A] },
                { key: 'flag-b', projectIds: [TARGET_B] },
            ],
            failed: [
                { key: 'flag-a', projectId: TARGET_B, errorMessage: 'Approval required', approvalPending: true },
                { key: 'flag-b', projectId: TARGET_A, errorMessage: 'Project not found.', approvalPending: undefined },
            ],
            warnings: ['flag-a: dropped', 'flag-b: no schedules'],
            skippedFlagCount: 0,
        })
    })

    it('records failures for every target of a key whose request throws and continues with the remaining keys', async () => {
        useCopyMocks((body) =>
            body.feature_flag_key === 'flag-a' ? [500, { detail: 'Server error' }] : successResponse('flag-b')
        )
        logic = flagSelectionLogic()
        logic.mount()

        logic.actions.openBulkCopyModal({ sourceProjectId: MOCK_TEAM_ID, flagKeys: ['flag-a', 'flag-b'] })
        logic.actions.setBulkCopyTargetProjectIds([TARGET_A, TARGET_B])
        logic.actions.bulkCopyFlags()
        await expectLogic(logic).toFinishAllListeners()

        expect(copyRequests).toHaveLength(2)
        expect(logic.values.bulkCopyResult?.copied).toEqual([{ key: 'flag-b', projectIds: [TARGET_A, TARGET_B] }])
        expect(logic.values.bulkCopyResult?.failed).toEqual([
            { key: 'flag-a', projectId: TARGET_A, errorMessage: 'Server error' },
            { key: 'flag-a', projectId: TARGET_B, errorMessage: 'Server error' },
        ])
    })

    it('refuses to run above the flag cap without issuing any copy requests', async () => {
        useCopyMocks((body) => successResponse(body.feature_flag_key))
        logic = flagSelectionLogic()
        logic.mount()

        const tooManyKeys = Array.from({ length: BULK_COPY_MAX_FLAGS + 1 }, (_, i) => `flag-${i}`)
        logic.actions.openBulkCopyModal({ sourceProjectId: MOCK_TEAM_ID, flagKeys: tooManyKeys })
        logic.actions.setBulkCopyTargetProjectIds([TARGET_A])
        logic.actions.bulkCopyFlags()
        await expectLogic(logic).toFinishAllListeners()

        expect(copyRequests).toHaveLength(0)
        expect(logic.values.bulkCopyResult).toBeNull()
        expect(logic.values.bulkCopyRunning).toBe(false)
    })
})
