import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'
import { ChangeRequest, ChangeRequestState, ValidationStatus } from '~/types'

import { ChangeRequestTableActions } from './ChangeRequestTableActions'

const pendingChangeRequest: ChangeRequest = {
    id: 'cr-1',
    action_key: 'feature_flag.enable',
    action_version: 1,
    resource_type: 'feature_flag',
    resource_id: '123',
    intent: { flag_key: 'my-flag' },
    intent_display: { description: 'Enable my-flag' },
    policy_snapshot: { quorum: 1, roles: ['role-1'], allow_self_approve: false },
    validation_status: ValidationStatus.Valid,
    validation_errors: null,
    validated_at: null,
    state: ChangeRequestState.Pending,
    created_by: { id: 1, uuid: 'user-1', distinct_id: 'distinct-1', first_name: 'Admin', email: 'admin@example.com' },
    applied_by: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    expires_at: '2026-01-15T00:00:00Z',
    applied_at: null,
    apply_error: '',
    result_data: null,
    approvals: [],
    can_approve: true,
    can_cancel: false,
    is_requester: false,
    user_decision: null,
}

describe('<ChangeRequestTableActions />', () => {
    beforeEach(() => {
        initKeaTests()
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            membership_level: OrganizationMembershipLevel.Member,
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('lets an organization member who is in the approver set approve from the row menu', async () => {
        const onApprove = jest.fn()
        const { container } = render(
            <ChangeRequestTableActions
                changeRequest={pendingChangeRequest}
                onApprove={onApprove}
                onReject={jest.fn()}
            />
        )

        await userEvent.click(container.querySelector('[data-attr="more-button"]') as HTMLElement)

        const approveButton = screen.getByText('Approve').closest('button') as HTMLButtonElement
        expect(approveButton).toHaveAttribute('aria-disabled', 'false')

        await userEvent.click(approveButton)
        const dialog = screen.getByText('Approve this change request?').closest('.LemonModal') as HTMLElement
        await userEvent.click(within(dialog).getByText('Approve'))

        expect(onApprove).toHaveBeenCalledWith('cr-1')
    })
})
