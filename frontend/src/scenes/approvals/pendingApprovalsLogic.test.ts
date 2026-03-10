import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ChangeRequest, ChangeRequestState } from '~/types'

import { pendingApprovalsLogic } from './pendingApprovalsLogic'

const MOCK_USER = { id: 1, first_name: 'Test', email: 'test@posthog.com', uuid: 'abc' }

function makeChangeRequest(overrides: Partial<ChangeRequest> = {}): ChangeRequest {
    return {
        id: 'cr-1',
        action_key: 'toggle_feature_flag',
        action_version: 1,
        resource_type: 'feature_flag',
        resource_id: '1',
        intent: {},
        intent_display: {},
        policy_snapshot: {},
        validation_status: 'valid' as any,
        validation_errors: null,
        validated_at: null,
        state: ChangeRequestState.Pending,
        created_by: MOCK_USER as any,
        applied_by: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        expires_at: '2026-01-08T00:00:00Z',
        applied_at: null,
        apply_error: '',
        result_data: null,
        approvals: [],
        can_approve: true,
        can_cancel: false,
        is_requester: false,
        user_decision: null,
        ...overrides,
    }
}

describe('pendingApprovalsLogic', () => {
    let logic: ReturnType<typeof pendingApprovalsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:teamId/change_requests': () => [200, { results: [] }],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('actionableChangeRequests', () => {
        it.each([
            {
                label: 'includes pending CRs where user can approve and has not decided',
                changeRequests: [makeChangeRequest()],
                expected: 1,
            },
            {
                label: 'excludes CRs where user cannot approve',
                changeRequests: [makeChangeRequest({ can_approve: false })],
                expected: 0,
            },
            {
                label: 'excludes CRs where user already decided',
                changeRequests: [makeChangeRequest({ user_decision: 'approved' })],
                expected: 0,
            },
            {
                label: 'excludes approved-state CRs even if user can approve',
                changeRequests: [makeChangeRequest({ state: ChangeRequestState.Approved })],
                expected: 0,
            },
            {
                label: 'filters correctly across mixed CRs',
                changeRequests: [
                    makeChangeRequest({ id: 'cr-1' }),
                    makeChangeRequest({ id: 'cr-2', can_approve: false }),
                    makeChangeRequest({ id: 'cr-3', user_decision: 'rejected' }),
                    makeChangeRequest({ id: 'cr-4', state: ChangeRequestState.Approved }),
                ],
                expected: 1,
            },
        ])('$label', async ({ changeRequests, expected }) => {
            logic = pendingApprovalsLogic()
            logic.mount()

            // Directly set loaded data to test selector logic independently of API/auth
            logic.actions.loadUnresolvedChangeRequestsSuccess(changeRequests)

            await expectLogic(logic).toMatchValues({ actionableCount: expected })
        })
    })

    describe('unresolvedCount', () => {
        it('counts all pending CRs regardless of can_approve', async () => {
            logic = pendingApprovalsLogic()
            logic.mount()

            logic.actions.loadUnresolvedChangeRequestsSuccess([
                makeChangeRequest({ id: 'cr-1', can_approve: true }),
                makeChangeRequest({ id: 'cr-2', can_approve: false }),
                makeChangeRequest({ id: 'cr-3', can_approve: false, user_decision: 'approved' }),
            ])

            await expectLogic(logic).toMatchValues({ unresolvedCount: 3, actionableCount: 1 })
        })
    })
})
