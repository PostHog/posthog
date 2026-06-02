import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { AppContext } from '../types'
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

    describe('custom asset selectors', () => {
        const mountWithAssets = (custom_assets: unknown[]): void => {
            window.POSTHOG_APP_CONTEXT = {
                current_user: { organization: { id: 'WXYZ', custom_assets } },
            } as unknown as AppContext
            initKeaTests()
            logic = organizationLogic()
            logic.mount()
        }

        it('customAssetByKey fetches an asset by key, scoped to the org', async () => {
            mountWithAssets([
                { id: '1', key: 'logo', url: '/organization_custom_asset/1', file_name: 'logo.png', enabled: true },
                { id: '2', key: 'hog', url: '/organization_custom_asset/2', file_name: 'hog.png', enabled: true },
            ])
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            expect(logic.values.customAssetByKey('logo')?.id).toBe('1')
            expect(logic.values.customAssetByKey('hog')?.id).toBe('2')
            expect(logic.values.customAssetByKey('missing')).toBeNull()
        })

        it('customLogo returns the enabled logo asset', async () => {
            mountWithAssets([{ id: '1', key: 'logo', url: '/x', file_name: null, enabled: true }])
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            expect(logic.values.customLogo?.id).toBe('1')
        })

        it('customLogo ignores a disabled logo asset, but it stays fetchable by key', async () => {
            mountWithAssets([{ id: '1', key: 'logo', url: '/x', file_name: null, enabled: false }])
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            expect(logic.values.customLogo).toBeNull()
            expect(logic.values.customAssetByKey('logo')?.id).toBe('1')
        })
    })
})
