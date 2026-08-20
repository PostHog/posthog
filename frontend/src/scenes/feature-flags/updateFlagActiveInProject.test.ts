import { showApprovalRequiredToast } from 'scenes/approvals/ApprovalRequiredBanner'
import { dispatchChangeRequestCreated } from 'scenes/approvals/utils'

import { useMocks } from '~/mocks/jest'

import { updateFlagActiveInProject } from './updateFlagActiveInProject'

jest.mock('scenes/approvals/ApprovalRequiredBanner', () => ({
    showApprovalRequiredToast: jest.fn(),
}))
jest.mock('scenes/approvals/utils', () => ({
    ...jest.requireActual('scenes/approvals/utils'),
    dispatchChangeRequestCreated: jest.fn(),
}))

describe('updateFlagActiveInProject', () => {
    it('shows the approval toast with the response code and announces the change request on a 409', async () => {
        useMocks({
            patch: {
                '/api/projects/:team_id/feature_flags/:id/': () => [
                    409,
                    { change_request_id: 'cr-1', code: 'change_request_pending' },
                ],
            },
        })

        const result = await updateFlagActiveInProject({ teamId: 2, flagId: 42, active: true })

        expect(result).toBeNull()
        expect(showApprovalRequiredToast).toHaveBeenCalledWith(
            'cr-1',
            'enable this feature flag',
            'change_request_pending'
        )
        expect(dispatchChangeRequestCreated).toHaveBeenCalledWith({ resourceType: 'feature_flag', resourceId: 42 })
    })
})
