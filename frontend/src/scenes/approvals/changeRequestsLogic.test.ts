import { ChangeRequest, ChangeRequestState } from '~/types'

import { getApproveDisabledReason } from './changeRequestsLogic'

function makeChangeRequest(overrides: Partial<ChangeRequest>): ChangeRequest {
    return {
        state: ChangeRequestState.Pending,
        can_approve: false,
        is_requester: false,
        user_decision: null,
        policy_snapshot: {},
        ...overrides,
    } as ChangeRequest
}

describe('getApproveDisabledReason', () => {
    it.each([
        ['null when the request is not pending', { state: ChangeRequestState.Approved, is_requester: true }, null],
        ['null when the user can approve and has not voted', { can_approve: true }, null],
        [
            'already-voted reason takes precedence over being the requester',
            { is_requester: true, user_decision: 'approved' },
            "You've already voted on this change request.",
        ],
        [
            'own-request reason when requester and self-approval is not allowed',
            { is_requester: true, policy_snapshot: { allow_self_approve: false } },
            "You can't approve a change request you created.",
        ],
        [
            'no-permission reason when a non-requester is not an approver',
            { is_requester: false, can_approve: false },
            "You don't have permission to approve this change request, based on your organization's approval policies.",
        ],
        [
            'no-permission reason when self-approval is allowed but the requester is not an approver',
            { is_requester: true, can_approve: false, policy_snapshot: { allow_self_approve: true } },
            "You don't have permission to approve this change request, based on your organization's approval policies.",
        ],
    ])('returns the %s', (_name, overrides, expected) => {
        expect(getApproveDisabledReason(makeChangeRequest(overrides as Partial<ChangeRequest>))).toBe(expected)
    })
})
