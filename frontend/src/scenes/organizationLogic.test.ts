import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AppContext, OrganizationType } from '../types'
import { organizationLogic } from './organizationLogic'

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
    describe('when a refresh of the organization fails', () => {
        const ORGANIZATION_WITH_TEAMS = {
            ...MOCK_DEFAULT_ORGANIZATION,
            teams: [
                { id: 1, name: 'Project one' },
                { id: 2, name: 'Project two' },
            ],
        } as unknown as OrganizationType

        beforeEach(() => {
            window.POSTHOG_APP_CONTEXT = {
                current_user: { organization: ORGANIZATION_WITH_TEAMS },
            } as unknown as AppContext
            initKeaTests()
            logic = organizationLogic()
            logic.mount()
        })

        it('keeps the organization it already has when the server errors', async () => {
            useMocks({ get: { '/api/organizations/@current': () => [500, { detail: 'nope' }] } })
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])

            logic.actions.loadCurrentOrganization()

            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            expect(logic.values.currentOrganization).toEqual(ORGANIZATION_WITH_TEAMS)
        })

        it('drops the organization when the server says it is out of reach', async () => {
            useMocks({ get: { '/api/organizations/@current': () => [403, { detail: 'nope' }] } })
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])

            logic.actions.loadCurrentOrganization()

            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            expect(logic.values.currentOrganization).toBeNull()
        })
    })

    describe('redirecting away from a blocked organization', () => {
        const mountWith = (organization: Partial<OrganizationType>): void => {
            window.POSTHOG_APP_CONTEXT = {
                current_user: { organization: { id: 'WXYZ', ...organization } },
            } as unknown as AppContext
            initKeaTests()
            logic = organizationLogic()
            logic.mount()
        }

        test.each([
            ['deactivated keeps an invite link', { is_active: false }, '/signup/abc', '/signup/abc'],
            ['deactivated keeps billing', { is_active: false }, '/organization/billing', '/organization/billing'],
            [
                'deactivated keeps the Stripe return route',
                { is_active: false },
                '/billing/authorization_status',
                '/billing/authorization_status',
            ],
            ['deactivated drops the app', { is_active: false }, '/dashboard', '/organization-deactivated'],
            ['pending deletion keeps an invite link', { is_pending_deletion: true }, '/signup/abc', '/signup/abc'],
            [
                'pending deletion drops billing',
                { is_pending_deletion: true },
                '/organization/billing',
                '/organization-pending-deletion',
            ],
        ])('%s', async (_name, organization, pathname, expected) => {
            mountWith(organization)
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])

            router.actions.push(pathname)

            await expectLogic(router).toDispatchActions(['push'])
            // The router writes back a `/project/<id>` prefix, so compare on the route.
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(expected)
        })
        it("keeps a client-side link into another organization's project", async () => {
            mountWith({ is_active: false, teams: [{ id: 1 }] } as unknown as Partial<OrganizationType>)
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])

            router.actions.push('/project/424242/dashboard')

            await expectLogic(router).toDispatchActions(['push'])
            expect(router.values.location.pathname).toBe('/project/424242/dashboard')
        })

        it('still blocks a link into a project the organization owns', async () => {
            mountWith({ is_active: false, teams: [{ id: 424242 }] } as unknown as Partial<OrganizationType>)
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])

            router.actions.push('/project/424242/dashboard')

            await expectLogic(router).toDispatchActions(['push'])
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe('/organization-deactivated')
        })
    })
})
