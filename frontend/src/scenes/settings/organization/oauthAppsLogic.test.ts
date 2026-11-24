import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { supportLogic } from 'lib/components/Support/supportLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { oauthAppsLogic } from './oauthAppsLogic'

const MOCK_APPS = [
    {
        id: 'app-1',
        name: 'MCP Cursor',
        client_id: 'client_abc',
        redirect_uris_list: ['https://cursor.sh/callback'],
        is_verified: true,
        is_cimd_client: false,
        provisioning_status: 'not_a_partner' as const,
        provisioning_review: null,
        created: '2026-01-15T10:00:00Z',
        updated: '2026-01-15T10:00:00Z',
    },
    {
        id: 'app-2',
        name: 'PostHog Toolbar',
        client_id: 'https://partner.example.com/.well-known/client.json',
        redirect_uris_list: ['https://partner.example.com/callback'],
        is_verified: false,
        is_cimd_client: true,
        provisioning_status: 'waiting_for_staff' as const,
        provisioning_review: {
            status: 'needs_human' as const,
            opened_at: '2026-01-10T10:00:00Z',
            decided_at: '2026-01-10T10:05:00Z',
            partner_message: '',
        },
        created: '2026-01-10T10:00:00Z',
        updated: '2026-01-10T10:00:00Z',
    },
]

describe('oauthAppsLogic', () => {
    let logic: ReturnType<typeof oauthAppsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/oauth_applications/': {
                    count: MOCK_APPS.length,
                    next: null,
                    previous: null,
                    results: MOCK_APPS,
                },
            },
        })
        initKeaTests(true, undefined, undefined, MOCK_DEFAULT_ORGANIZATION)
        logic = oauthAppsLogic()
        logic.mount()
    })

    it('loads OAuth apps on mount', async () => {
        await expectLogic(logic).toDispatchActions(['loadOAuthApps', 'loadOAuthAppsSuccess']).toMatchValues({
            oauthApps: MOCK_APPS,
            oauthAppsLoading: false,
        })
    })

    it('starts unresolved, so the page does not show the empty state before the first answer', () => {
        initKeaTests(true, undefined, undefined, MOCK_DEFAULT_ORGANIZATION)
        const freshLogic = oauthAppsLogic()
        freshLogic.mount()

        expect(freshLogic.values.oauthApps).toBeNull()
        expect(freshLogic.values.oauthAppsLoading).toEqual(true)
    })

    it('reports a failed load, and clears it when a retry succeeds', async () => {
        useMocks({ get: { '/api/organizations/:organization_id/oauth_applications/': () => [500, {}] } })
        logic.actions.loadOAuthApps()
        await expectLogic(logic).toDispatchActions(['loadOAuthAppsFailure']).toMatchValues({
            oauthApps: MOCK_APPS,
            oauthAppsLoadFailed: true,
        })

        useMocks({
            get: { '/api/organizations/:organization_id/oauth_applications/': { results: MOCK_APPS } },
        })
        logic.actions.loadOAuthApps()

        await expectLogic(logic).toDispatchActions(['loadOAuthAppsSuccess']).toMatchValues({
            oauthAppsLoadFailed: false,
        })
    })

    it.each([
        ['review', 'provisioning review', 'Waiting for PostHog staff'],
        ['verification', 'verify our OAuth application', "Our product's website:"],
    ] as const)('opens a %s request that any plan can send', async (request, opening, prompt) => {
        supportLogic.mount()

        logic.actions.contactSupport(MOCK_APPS[1], request)

        const form = supportLogic.values.sendSupportRequest
        expect(form.oauth_app_request).toBe(true)
        expect(form.message).toContain(opening)
        expect(form.message).toContain(MOCK_APPS[1].client_id)
        expect(form.message).toContain(prompt)
    })
})
