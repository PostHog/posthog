jest.mock('scenes/userLogic', () => require('~/toolbar/shims/userLogic'))
jest.mock('scenes/organization/membersLogic', () => require('~/toolbar/shims/membersLogic'))
jest.mock('scenes/sceneLogic', () => require('~/toolbar/shims/sceneLogic'))
jest.mock('scenes/teamLogic', () => require('~/toolbar/shims/teamLogic'))
jest.mock('lib/logic/featureFlagLogic', () => require('~/toolbar/shims/featureFlagLogic'))
jest.mock('lib/api', () => ({
    __esModule: true,
    default: { get: jest.fn().mockResolvedValue(null), update: jest.fn().mockResolvedValue(null) },
}))

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { AppContext } from '~/types'

global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
    } as any as Response)
)

describe('shim consumer integration', () => {
    beforeEach(() => {
        // The toolbar runs on third-party pages without an authenticated PostHog user, so
        // hedgehogModeLogic.values.user must be null. We pre-set current_user: null here because
        // initKeaTests now bootstraps a default org into current_user (to mirror production).
        // Without this, the real userLogic (which gets mounted despite the jest.mock shim)
        // would read that bootstrapped user and leak it into hedgehogModeLogic.
        window.POSTHOG_APP_CONTEXT = { current_user: null } as unknown as AppContext
        initKeaTests(false)
        toolbarConfigLogic.build({ apiURL: 'http://localhost' }).mount()
        jest.clearAllMocks()
    })

    describe('hedgehogModeLogic with shims', () => {
        // MSW installs a never-resolving global.fetch in a beforeAll and never restores it per test,
        // so a test that swaps global.fetch must put it back or the swap leaks into later tests.
        let restoreFetch: (() => void) | undefined
        afterEach(() => {
            restoreFetch?.()
            restoreFetch = undefined
        })

        it('mounts without error and has shimmed defaults', async () => {
            const { hedgehogModeLogic } = await import('~/lib/components/HedgehogMode/hedgehogModeLogic')
            const logic = hedgehogModeLogic.build()

            expect(() => logic.mount()).not.toThrow()
            expect(logic.values.hedgehogMode).toBeNull()
            expect(logic.values.user).toBeNull()
        })

        it('afterMount falls through to loadRemoteConfig when shimmed user is null', async () => {
            const { hedgehogModeLogic } = await import('~/lib/components/HedgehogMode/hedgehogModeLogic')
            const logic = hedgehogModeLogic.build()

            await expectLogic(logic, () => {
                logic.mount()
            }).toDispatchActions(['loadRemoteConfig'])
        })

        it('does not PATCH hedgehog_config from the Toolbar, keeping the session alive', async () => {
            // The Toolbar OAuth token is scoped to `user:read` but not `user:write`, so the real
            // backend 403s the PATCH while the GET still succeeds. toolbarFetch turns any 403 into a
            // session reset, which used to log the user out of the Toolbar whenever hedgehog mode
            // moved the hedgehog around. Swap in our own mock and let afterEach restore the original.
            const originalFetch = global.fetch
            restoreFetch = () => {
                global.fetch = originalFetch
            }
            const fetchMock = jest.fn((_url: string, options?: RequestInit) =>
                Promise.resolve({
                    ok: options?.method !== 'PATCH',
                    status: options?.method === 'PATCH' ? 403 : 200,
                    json: () => Promise.resolve({}),
                } as Response)
            )
            global.fetch = fetchMock as unknown as typeof fetch

            // Authenticate the Toolbar session — this is the path that used to break.
            toolbarConfigLogic.actions.setOAuthTokens('access-token', 'refresh-token', 'client-id')
            expect(toolbarConfigLogic.values.isAuthenticated).toBe(true)

            const { hedgehogModeLogic } = await import('~/lib/components/HedgehogMode/hedgehogModeLogic')
            const logic = hedgehogModeLogic.build()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.updateRemoteConfig({ enabled: true })
            }).toDispatchActions(['updateRemoteConfigSuccess'])

            // The write must never hit the network — a 403 there resets the Toolbar session.
            const patchCalls = fetchMock.mock.calls.filter(([, options]) => options?.method === 'PATCH')
            expect(patchCalls).toHaveLength(0)

            // Session survives: the user is not kicked out of the Toolbar.
            expect(toolbarConfigLogic.values.isAuthenticated).toBe(true)

            // The change is still applied locally so the hedgehog reflects it this session.
            expect(logic.values.remoteConfig).toMatchObject({ enabled: true })

            logic.unmount()
        })
    })

    describe('themeLogic with shims', () => {
        it('mounts without error and provides isDarkModeOn', async () => {
            const { themeLogic } = await import('~/layout/navigation-3000/themeLogic')
            const logic = themeLogic.build()
            logic.mount()

            expect(typeof logic.values.isDarkModeOn).toBe('boolean')
        })

        it('isDarkModeOn falls through to system preference when sceneConfig is null', async () => {
            const { themeLogic } = await import('~/layout/navigation-3000/themeLogic')
            const logic = themeLogic.build()
            logic.mount()

            const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
            expect(logic.values.isDarkModeOn).toBe(systemPrefersDark)
        })
    })

    describe('teamLogic shim contract', () => {
        it('provides weekStartDay for DateFilter', () => {
            const { teamLogic } = require('scenes/teamLogic')
            teamLogic.mount()
            expect(teamLogic.values.weekStartDay).toBe(0)
            expect(teamLogic.values.timezone).toBe('UTC')
        })
    })
})
