import { expectLogic } from 'kea-test-utils'

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
        created: '2026-01-15T10:00:00Z',
        updated: '2026-01-15T10:00:00Z',
    },
    {
        id: 'app-2',
        name: 'PostHog Toolbar',
        client_id: 'client_xyz',
        redirect_uris_list: ['https://app.posthog.com/toolbar'],
        is_verified: false,
        created: '2026-01-10T10:00:00Z',
        updated: '2026-01-10T10:00:00Z',
    },
]

describe('oauthAppsLogic', () => {
    let logic: ReturnType<typeof oauthAppsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/@current/oauth_applications/': {
                    count: MOCK_APPS.length,
                    next: null,
                    previous: null,
                    results: MOCK_APPS,
                },
            },
        })
        initKeaTests()
        logic = oauthAppsLogic()
        logic.mount()
    })

    it('loads OAuth apps on mount', async () => {
        await expectLogic(logic).toDispatchActions(['loadOAuthApps', 'loadOAuthAppsSuccess']).toMatchValues({
            oauthApps: MOCK_APPS,
            oauthAppsLoading: false,
        })
    })

    it('starts with empty array and loading state', () => {
        initKeaTests()
        useMocks({
            get: {
                '/api/organizations/@current/oauth_applications/': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
            },
        })
        const freshLogic = oauthAppsLogic()
        freshLogic.mount()

        expect(freshLogic.values.oauthApps).toEqual([])
    })
})
