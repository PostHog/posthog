import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { AppContext } from '../types'
import { organizationLogic } from './organizationLogic'
import { urls } from './urls'

describe('organizationLogic', () => {
    let logic: ReturnType<typeof organizationLogic.build>

    describe('if POSTHOG_APP_CONTEXT available', () => {
        beforeEach(() => {
            window.POSTHOG_APP_CONTEXT = { current_user: { organization: { id: 'WXYZ' } } } as unknown as AppContext
            initKeaTests()
            logic = organizationLogic()
            logic.mount()
        })

        it('loads organization from window', async () => {
            await expectLogic(logic).toNotHaveDispatchedActions(['loadCurrentOrganization'])
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            await expectLogic(logic).toMatchValues({
                currentOrganization: { id: 'WXYZ' },
            })
        })

        it('currentOrganizationId returns the id when loaded', async () => {
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            expect(logic.values.currentOrganizationId).toBe('WXYZ')
        })
    })

    describe('currentOrganizationId before load', () => {
        it('returns @current fallback when currentOrganization is null', () => {
            // Clear the user/organization context so currentOrganization starts as null
            window.POSTHOG_APP_CONTEXT = { current_user: null } as unknown as AppContext
            initKeaTests(false)
            logic = organizationLogic()
            logic.mount()
            expect(logic.values.currentOrganizationId).toBe('@current')
        })
    })

    describe('if POSTHOG_APP_CONTEXT is undefined', () => {
        // Should not happen in production, but the app should still not break.
        // We use initKeaTests(false) to set up the kea environment, then reset the context to undefined
        // so organizationLogic sees the real undefined case when it mounts.
        beforeEach(() => {
            initKeaTests(false)
            window.POSTHOG_APP_CONTEXT = undefined as unknown as AppContext
            logic = organizationLogic()
            logic.mount()
        })
        it('falls back to loading organization from API', async () => {
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganization', 'loadCurrentOrganizationSuccess'])
            await expectLogic(logic).toMatchValues({
                currentOrganization: { ...MOCK_DEFAULT_ORGANIZATION },
            })
        })
    })

    describe('pending deletion lockout redirect', () => {
        beforeEach(async () => {
            window.POSTHOG_APP_CONTEXT = {
                current_user: { organization: { id: 'WXYZ', is_pending_deletion: true } },
            } as unknown as AppContext
            initKeaTests()
            logic = organizationLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
        })

        it('redirects to the lockout screen from another route', async () => {
            router.actions.push(urls.settings('organization'))
            await expectLogic(router).toDispatchActions(['replace'])
            expect(router.values.location.pathname.endsWith(urls.organizationPendingDeletion())).toBe(true)
        })

        it('does not redirect when already on the prefixed lockout screen', async () => {
            // Client-side navigation adds a /project/:id prefix; the guard must match by suffix or it loops.
            const prefixedPath = `/project/121874${urls.organizationPendingDeletion()}`
            router.actions.push(prefixedPath)
            await expectLogic(logic).toFinishAllListeners()
            expect(router.values.location.pathname).toEqual(prefixedPath)
        })
    })

    describe('pending deletion takes priority over inactive lockout', () => {
        beforeEach(async () => {
            window.POSTHOG_APP_CONTEXT = {
                current_user: { organization: { id: 'WXYZ', is_pending_deletion: true, is_active: false } },
            } as unknown as AppContext
            initKeaTests()
            logic = organizationLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
        })

        it('does not redirect to deactivated when already on the prefixed pending path', async () => {
            // With both flags set the inactive guard must not fire on the pending path, or the two guards loop.
            const prefixedPath = `/project/121874${urls.organizationPendingDeletion()}`
            router.actions.push(prefixedPath)
            await expectLogic(logic).toFinishAllListeners()
            expect(router.values.location.pathname).toEqual(prefixedPath)
        })
    })

    describe('if organization not in POSTHOG_APP_CONTEXT', () => {
        // In production POSTHOG_APP_CONTEXT is always present (server-rendered in posthog/templates/head.html),
        // but current_user is null for unauthenticated requests such as shared dashboards (see posthog/utils.py).
        // That is the real trigger for the async API load path.
        beforeEach(async () => {
            window.POSTHOG_APP_CONTEXT = { current_user: null } as unknown as AppContext
            initKeaTests()
            logic = organizationLogic()
            logic.mount()
        })
        it('loads organization from API', async () => {
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganization', 'loadCurrentOrganizationSuccess'])
            await expectLogic(logic).toMatchValues({
                currentOrganization: { ...MOCK_DEFAULT_ORGANIZATION },
            })
        })
    })
})
