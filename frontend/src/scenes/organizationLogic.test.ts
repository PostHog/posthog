import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import type { LocationChangedPayload } from 'kea-router/lib/types'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { AppContext, OrganizationType } from '../types'
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

    describe('lockout redirects on locationChanged', () => {
        const mountWithOrganization = async (organization: Partial<OrganizationType>): Promise<void> => {
            initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, {
                ...MOCK_DEFAULT_ORGANIZATION,
                ...organization,
            })
            logic = organizationLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
        }

        // Regression guard: the redirect used to recurse infinitely ("Maximum call stack size
        // exceeded") because the replaced pathname came back with a /project/<id> prefix and
        // never matched the bare lockout URL.
        it.each<[string, Partial<OrganizationType>, string]>([
            ['pending deletion', { is_pending_deletion: true }, urls.organizationPendingDeletion()],
            ['deactivated', { is_active: false }, urls.organizationDeactivated()],
        ])(
            'navigation while the organization is %s settles on its bare lockout page',
            async (_label, organization, lockoutPath) => {
                await mountWithOrganization(organization)

                router.actions.push('/dashboard')

                expect(router.values.location.pathname).toEqual(lockoutPath)
            }
        )

        it('does not redirect again when already on the lockout page', async () => {
            await mountWithOrganization({ is_pending_deletion: true })

            router.actions.push(urls.organizationPendingDeletion())

            expect(router.values.location.pathname).toEqual(urls.organizationPendingDeletion())
            await expectLogic(router).toNotHaveDispatchedActions(['replace'])
        })

        it('does not rewrite history on a POP to a legacy project-prefixed lockout URL', async () => {
            await mountWithOrganization({ is_pending_deletion: true })
            const prefixedLockoutUrl = `/project/${MOCK_DEFAULT_TEAM.id}${urls.organizationPendingDeletion()}`

            // POP events (browser back/forward) bypass the router's path transforms, so the
            // pathname can still carry a prefix recorded by an older client.
            router.actions.locationChanged({
                method: 'POP',
                pathname: prefixedLockoutUrl,
                search: '',
                searchParams: {},
                hash: '',
                hashParams: {},
                url: prefixedLockoutUrl,
            } as LocationChangedPayload)

            await expectLogic(router).toNotHaveDispatchedActions(['replace'])
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
