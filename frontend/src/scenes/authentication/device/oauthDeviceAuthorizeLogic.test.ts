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
        [
            'a first login lists every requested scope',
            [],
            ['View your User ID', 'Write access to insights', 'Write access to dashboards'],
            false,
        ],
        [
            'a login that adds nothing, like one for another project, lists every scope',
            ['openid', 'insight:read', 'insight:write', 'dashboard:write'],
            ['View your User ID', 'Write access to insights', 'Write access to dashboards'],
            false,
        ],
        [
            'a step-up lists only the scopes it adds',
            ['openid', 'insight:read'],
            ['Write access to insights', 'Write access to dashboards'],
            true,
        ],
    ])('%s', async (_name, grantedScopes, expectedDescriptions, isStepUp) => {
        useGrantMocks({ ...GRANT, granted_scopes: grantedScopes })
        const logic = oauthDeviceAuthorizeLogic()
        logic.mount()

        router.actions.push(urls.oauthDeviceAuthorize(), { code: 'bcdf-ghjk' })
        await expectLogic(logic).toFinishAllListeners()

        expect(lookups).toEqual(['BCDF-GHJK'])
        await expectLogic(logic).toMatchValues({ isStepUp, scopeDescriptions: expectedDescriptions })
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

        expect(approvals).toEqual([{ user_code: 'BCDF-GHJK', project_id: 42 }])
        await expectLogic(logic).toMatchValues({ decision: 'authorized' })
    })
})
