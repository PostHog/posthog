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

    describe('lifecycle redirects', () => {
        const mountWithOrg = (org: Record<string, unknown>): void => {
            // Mirror production for a deactivated / pending-deletion org: there is no current team,
            // so navigation paths stay un-prefixed (no /project/<id>) and the guards can compare them
            // against the bare lifecycle URLs.
            initKeaTests(false)
            window.POSTHOG_APP_CONTEXT = {
                current_team: null,
                current_user: { organization: { id: 'WXYZ', ...org } },
            } as unknown as AppContext
            logic = organizationLogic()
            logic.mount()
        }

        it('routes a pending-deletion org to the pending deletion page', async () => {
            mountWithOrg({ is_pending_deletion: true })
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            router.actions.push(urls.settings())
            expect(router.values.location.pathname).toBe(urls.organizationPendingDeletion())
        })

        it('routes an inactive org to the deactivated page', async () => {
            mountWithOrg({ is_active: false })
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            router.actions.push(urls.settings())
            expect(router.values.location.pathname).toBe(urls.organizationDeactivated())
        })

        it('keeps a pending-deletion AND inactive org on the pending deletion page without looping', async () => {
            // Regression: both guards used to fight each other and ping-pong until the call stack overflowed.
            mountWithOrg({ is_pending_deletion: true, is_active: false })
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            router.actions.push(urls.organizationDeactivated())
            expect(router.values.location.pathname).toBe(urls.organizationPendingDeletion())
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
