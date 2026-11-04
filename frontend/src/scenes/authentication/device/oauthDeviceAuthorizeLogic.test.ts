import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import type { DeviceGrantDetailsApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { oauthDeviceAuthorizeLogic } from './oauthDeviceAuthorizeLogic'

const GRANT: DeviceGrantDetailsApi = {
    user_code: 'BCDF-GHJK',
    client_id: 'https://posthog.com/.well-known/oauth/hog/client-metadata.json',
    client_name: 'hog',
    logo_uri: null,
    is_verified: false,
    scopes: ['openid', 'insight:read', 'insight:write', 'dashboard:write'],
    required_scopes: ['openid'],
    granted_scopes: [],
    expires_at: '2026-03-02T10:30:00Z',
}

describe('oauthDeviceAuthorizeLogic', () => {
    let lookups: string[]
    let approvals: unknown[]

    function useGrantMocks(grant: DeviceGrantDetailsApi): void {
        useMocks({
            post: {
                '/api/oauth_device/lookup/': async ({ request }) => {
                    lookups.push(((await request.json()) as { user_code: string }).user_code)
                    return [200, grant]
                },
                '/api/oauth_device/approve/': async ({ request }) => {
                    approvals.push(await request.json())
                    return [200, { status: 'authorized' }]
                },
            },
        })
    }

    beforeEach(() => {
        lookups = []
        approvals = []
        initKeaTests()
    })

    it.each([
        ['a first login', [], false],
        [
            'a login that adds nothing in the project',
            [
                {
                    project_id: 42,
                    organization_id: null,
                    scopes: ['openid', 'insight:read', 'insight:write', 'dashboard:write'],
                },
            ],
            false,
        ],
        ['a step-up', [{ project_id: 42, organization_id: null, scopes: ['openid', 'insight:read'] }], true],
        [
            'a login after a grant in another organization',
            [{ project_id: null, organization_id: 'another-org', scopes: ['openid', 'insight:read'] }],
            false,
        ],
        [
            'a login after a grant in another project',
            [{ project_id: 7, organization_id: null, scopes: ['openid', 'insight:read'] }],
            false,
        ],
    ])('%s lets the person lower every scope the client does not require', async (_name, grantedScopes, isStepUp) => {
        useGrantMocks({ ...GRANT, granted_scopes: grantedScopes })
        const logic = oauthDeviceAuthorizeLogic()
        logic.mount()

        router.actions.push(urls.oauthDeviceAuthorize(), { code: 'bcdf-ghjk' })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setProjectId(42)

        expect(lookups).toEqual(['BCDF-GHJK'])
        expect(logic.values.scopeRows.map((row) => [row.key, row.minLevel])).toEqual([
            ['dashboard', 'none'],
            ['insight', 'none'],
        ])
        await expectLogic(logic).toMatchValues({ isStepUp, scopeSummary: 'hog can view and change data in 2 areas.' })
    })

    it('approves only the scopes the person kept, at the level they picked', async () => {
        useGrantMocks(GRANT)
        const logic = oauthDeviceAuthorizeLogic()
        logic.mount()
        router.actions.push(urls.oauthDeviceAuthorize(), { code: 'bcdf-ghjk' })
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setProjectId(42)
        logic.actions.setScopeAccess('dashboard', 'none')
        logic.actions.setScopeAccess('insight', 'read')
        logic.actions.approve()
        await expectLogic(logic).toFinishAllListeners()

        expect(approvals).toEqual([{ user_code: 'BCDF-GHJK', project_id: 42, scopes: ['openid', 'insight:read'] }])
        await expectLogic(logic).toMatchValues({ scopeSummary: 'hog can view data in 1 area.' })
    })

    it("drops the previous organization's projects when the next ones fail to load", async () => {
        useMocks({
            get: {
                '/api/organizations/:organizationId/projects/': ({ params }) =>
                    params.organizationId === 'org-a'
                        ? [200, { results: [{ id: 1, name: 'A project' }], next: null }]
                        : [500, { detail: 'boom' }],
            },
        })
        const logic = oauthDeviceAuthorizeLogic()
        logic.mount()
        logic.actions.setOrganizationId('org-a')
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setOrganizationId('org-b')
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic).toMatchValues({ projects: [], projectsError: expect.any(String) })
    })

    it('approves the code the server returned, for the project the person picked', async () => {
        useGrantMocks(GRANT)
        const logic = oauthDeviceAuthorizeLogic()
        logic.mount()
        router.actions.push(urls.oauthDeviceAuthorize(), { code: 'bcdf ghjk' })
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setProjectId(42)
        logic.actions.approve()
        await expectLogic(logic).toFinishAllListeners()

        expect(approvals).toEqual([
            {
                user_code: 'BCDF-GHJK',
                project_id: 42,
                scopes: ['openid', 'dashboard:write', 'insight:read', 'insight:write'],
            },
        ])
        await expectLogic(logic).toMatchValues({ decision: 'authorized' })
    })

    it('goes back to code entry when the code expired during review', async () => {
        useMocks({
            post: {
                '/api/oauth_device/lookup/': () => [200, GRANT],
                '/api/oauth_device/approve/': () => [
                    400,
                    { error: 'invalid_code', error_description: 'This code is wrong, expired or already used.' },
                ],
            },
        })
        const logic = oauthDeviceAuthorizeLogic()
        logic.mount()
        router.actions.push(urls.oauthDeviceAuthorize(), { code: 'bcdf-ghjk' })
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setProjectId(42)
        logic.actions.approve()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic).toMatchValues({
            deviceGrant: null,
            error: 'This code is wrong, expired or already used.',
        })
    })
})
