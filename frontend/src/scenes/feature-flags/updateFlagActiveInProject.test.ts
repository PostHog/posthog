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
        { version: undefined, expectedBody: { active: true } },
        { version: 4, expectedBody: { active: true, version: 4 } },
    ])('sends $expectedBody when the row version is $version', async ({ version, expectedBody }) => {
        let body: unknown
        useMocks({
            patch: {
                '/api/projects/:team_id/feature_flags/:id/': async ({ request }) => {
                    body = await request.json()
                    return [200, { id: 42, active: true, version: (version ?? 0) + 1 }]
                },
            },
        })

        const result = await updateFlagActiveInProject({
            teamId: 2,
            flagId: 42,
            active: true,
            version,
            filters: { groups: [] },
        })

        expect(body).toEqual(expectedBody)
        expect(result?.version).toBe((version ?? 0) + 1)
    })

    it('fetches the row version first when the row is in another config version', async () => {
        const calls: string[] = []
        let body: unknown
        useMocks({
            get: {
                '/api/projects/:team_id/feature_flags/:id/': () => {
                    calls.push('get')
                    return [200, { id: 42, active: false, version: 9, filters: V2_FILTERS }]
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

        await updateFlagActiveInProject({
            teamId: 2,
            flagId: 42,
            active: true,
            filters: V2_FILTERS,
        })

        expect(calls).toEqual(['get', 'patch'])
        expect(body).toEqual({ active: true, version: 9 })
    })

    it.each([
        { stored: { groups: [] }, expectedBody: { active: true } },
        { stored: V2_FILTERS, expectedBody: { active: true, version: 9 } },
    ])('fetches a row of unknown format first and sends $expectedBody', async ({ stored, expectedBody }) => {
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

        await updateFlagActiveInProject({ teamId: 2, flagId: 42, active: true })

        expect(calls).toEqual(['get', 'patch'])
        expect(body).toEqual(expectedBody)
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
