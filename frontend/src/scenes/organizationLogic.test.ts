import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AppContext, OrganizationType, PreflightStatus } from '../types'
import { organizationLogic } from './organizationLogic'

describe('organizationLogic', () => {
    let logic: ReturnType<typeof organizationLogic.build>

    test.each([
        ['hobby at its single-project limit', false, false, false, true, true],
        ['hobby before its first project', false, false, false, false, false],
        ['hobby with a legacy project entitlement', false, false, false, true, true],
        ['hobby with no visible teams', false, false, false, true, true],
        ['cloud without a project entitlement', true, false, false, true, false],
        ['local development', false, true, false, true, false],
        ['test mode', false, false, true, true, false],
    ])('%s', (_name, cloud, is_debug, is_test, hasProject, blocked) => {
        const organization: OrganizationType = {
            ...MOCK_DEFAULT_ORGANIZATION,
            teams: [],
            has_non_demo_project: hasProject,
        }
        window.POSTHOG_APP_CONTEXT = { current_user: { organization } } as unknown as AppContext
        initKeaTests()
        preflightLogic.actions.loadPreflightSuccess({ cloud, is_debug, is_test } as PreflightStatus)
        logic = organizationLogic()

        expect(Boolean(logic.values.projectCreationForbiddenReason)).toBe(blocked)
        if (blocked) {
            expect(logic.values.projectCreationForbiddenReason).toContain('Self-hosted PostHog supports one project')
        }
    })

    test('project creation waits for preflight settings', () => {
        const organization: OrganizationType = {
            ...MOCK_DEFAULT_ORGANIZATION,
            has_non_demo_project: false,
        }
        window.POSTHOG_APP_CONTEXT = { current_user: { organization } } as unknown as AppContext
        initKeaTests()
        logic = organizationLogic()

        expect(logic.values.projectCreationForbiddenReason).toContain('settings load')

        preflightLogic.actions.loadPreflightSuccess({
            cloud: false,
            is_debug: false,
            is_test: false,
        } as PreflightStatus)
        expect(logic.values.projectCreationForbiddenReason).toBeNull()
    })

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
            ['deactivated keeps an invite link', { is_active: false }, '/signup/abc', true],
            ['deactivated keeps billing', { is_active: false }, '/organization/billing', true],
            ['deactivated keeps the Stripe return route', { is_active: false }, '/billing/authorization_status', true],
            [
                'deactivated keeps its own page under a project prefix',
                { is_active: false },
                '/project/1/organization-deactivated',
                true,
            ],
            ['deactivated drops the app', { is_active: false }, '/dashboard', false],
            ['pending deletion keeps an invite link', { is_pending_deletion: true }, '/signup/abc', true],
            ['pending deletion drops billing', { is_pending_deletion: true }, '/organization/billing', false],
        ])('%s', async (_name, organization, pathname, open) => {
            mountWith(organization as unknown as Partial<OrganizationType>)
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])

            expect(logic.values.isPathOpenWhileBlocked(pathname)).toBe(open)
        })

        test.each([
            ["another organization's project", [{ id: 1 }], true],
            ['a project the organization owns', [{ id: 424242 }], false],
            ['a project while the team list is unknown', undefined, false],
        ])('a link into %s leaves the organization: %s', async (_name, teams, leaves) => {
            mountWith({ is_active: false, teams } as unknown as Partial<OrganizationType>)
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])

            expect(logic.values.isPathInAnotherOrganization('/project/424242/dashboard')).toBe(leaves)
        })
    })
})
