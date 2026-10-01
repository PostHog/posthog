import { showApprovalRequiredToast } from 'scenes/approvals/ApprovalRequiredBanner'
import { dispatchChangeRequestCreated } from 'scenes/approvals/utils'

import { useMocks } from '~/mocks/jest'
import { FeatureFlagConfig } from '~/types'

import { updateFlagActiveInProject } from './updateFlagActiveInProject'

jest.mock('scenes/approvals/ApprovalRequiredBanner', () => ({
    showApprovalRequiredToast: jest.fn(),
}))
jest.mock('scenes/approvals/utils', () => ({
    ...jest.requireActual('scenes/approvals/utils'),
    dispatchChangeRequestCreated: jest.fn(),
}))

const V2_FILTERS: FeatureFlagConfig = { version: 2, return_type: 'boolean', default_value: false, rules: [] }

describe('updateFlagActiveInProject', () => {
    it.each([
        { case: 'a v1 row', filters: { groups: [] }, stored: undefined, calls: ['patch'], body: { active: true } },
        {
            case: 'a row in another config version',
            filters: V2_FILTERS,
            stored: V2_FILTERS,
            calls: ['get', 'patch'],
            body: { active: true, version: 9 },
        },
        {
            case: 'a v1 row of unknown format',
            filters: undefined,
            stored: { groups: [] },
            calls: ['get', 'patch'],
            body: { active: true },
        },
        {
            case: 'a v2 row of unknown format',
            filters: undefined,
            stored: V2_FILTERS,
            calls: ['get', 'patch'],
            body: { active: true, version: 9 },
        },
    ])('sends $body for $case', async ({ filters, stored, calls: expectedCalls, body: expectedBody }) => {
        const calls: string[] = []
        let body: unknown
        useMocks({
            get: {
                '/api/projects/:team_id/feature_flags/:id/': () => {
                    calls.push('get')
                    return [200, { id: 42, active: false, version: 9, filters: stored }]
                },
            },
            patch: {
                '/api/projects/:team_id/feature_flags/:id/': async ({ request }) => {
                    calls.push('patch')
                    body = await request.json()
                    return [200, { id: 42, active: true, version: 10 }]
                },
            },
        })

        const result = await updateFlagActiveInProject({ teamId: 2, flagId: 42, active: true, filters })

        expect(calls).toEqual(expectedCalls)
        expect(body).toEqual(expectedBody)
        expect(result?.version).toBe(10)
    })

    it('shows the approval toast with the response code and announces the change request on a 409', async () => {
        useMocks({
            patch: {
                '/api/projects/:team_id/feature_flags/:id/': () => [
                    409,
                    { change_request_id: 'cr-1', code: 'change_request_pending' },
                ],
            },
        })

        const result = await updateFlagActiveInProject({ teamId: 2, flagId: 42, active: true, filters: { groups: [] } })

        expect(result).toBeNull()
        expect(showApprovalRequiredToast).toHaveBeenCalledWith(
            'cr-1',
            'enable this feature flag',
            'change_request_pending'
        )
        expect(dispatchChangeRequestCreated).toHaveBeenCalledWith({ resourceType: 'feature_flag', resourceId: 42 })
    })
})
