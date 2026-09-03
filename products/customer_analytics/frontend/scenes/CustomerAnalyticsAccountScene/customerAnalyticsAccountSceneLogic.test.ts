import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { AccountsEvents } from 'products/customer_analytics/frontend/components/Accounts/constants'
import { accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsRetrieve: jest.fn(),
}))

const mockAccountsRetrieve = accountsRetrieve as jest.MockedFunction<typeof accountsRetrieve>

const ACCOUNT_ID = '0190da51-0b0e-7000-8000-000000000001'
const account: AccountApi = {
    id: ACCOUNT_ID,
    name: 'Test account',
    external_id: 'test-account-external-id',
    tags: [],
    notebooks: [],
    ignored_at: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: null,
}

describe('customerAnalyticsAccountSceneLogic', () => {
    let logic: ReturnType<typeof customerAnalyticsAccountSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true,
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS]: true,
        })
        router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID))
        logic = customerAnalyticsAccountSceneLogic({ accountId: ACCOUNT_ID })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        featureFlagLogic.unmount()
    })

    it('loads the account and uses its name in the breadcrumb', async () => {
        mockAccountsRetrieve.mockResolvedValue(account)

        logic.actions.loadAccount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.account).toEqual(account)
        expect(logic.values.accountLoadError).toBeNull()
        expect(logic.values.breadcrumbs.at(-1)?.name).toBe(account.name)
    })

    it('classifies a missing account without reporting an exception', async () => {
        const captureException = jest.spyOn(posthog, 'captureException')
        mockAccountsRetrieve.mockRejectedValue(new ApiError('Not found', 404))

        logic.actions.loadAccount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isAccountMissing).toBe(true)
        expect(captureException).not.toHaveBeenCalled()
    })

    it('reports unexpected load failures', async () => {
        const failure = new ApiError('Server error', 500)
        const captureException = jest.spyOn(posthog, 'captureException')
        mockAccountsRetrieve.mockRejectedValue(failure)

        logic.actions.loadAccount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isAccountMissing).toBe(false)
        expect(logic.values.accountLoadError).toBe(failure)
        expect(captureException).toHaveBeenCalledWith(failure, {
            scope: 'customerAnalyticsAccountSceneLogic.loadAccount',
        })
    })

    it('clears a previous error when retrying', async () => {
        mockAccountsRetrieve.mockRejectedValueOnce(new ApiError('Server error', 500))

        logic.actions.loadAccount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.accountLoadError).toBeInstanceOf(ApiError)

        let resolveAccount: (value: AccountApi) => void
        mockAccountsRetrieve.mockReturnValueOnce(
            new Promise<AccountApi>((resolve) => {
                resolveAccount = resolve
            })
        )

        logic.actions.loadAccount()
        expect(logic.values.accountLoadError).toBeNull()

        resolveAccount!(account)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.account).toEqual(account)
    })

    describe('tab routing', () => {
        it('selects Notes for the bare account URL', () => {
            router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID))

            expect(logic.values.activeTab).toBe('notes')
        })

        it.each(['users', 'usage', 'feature_requests'] as const)('selects the %s tab from the URL', (tab) => {
            router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID, tab))

            expect(logic.values.activeTab).toBe(tab)
        })

        it('selects Notes for an unknown tab', () => {
            router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID, 'unknown'))

            expect(logic.values.activeTab).toBe('notes')
        })

        it('selects Notes for a feature-flag-hidden tab', () => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true,
            })
            router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID, 'feature_requests'))

            expect(logic.values.activeTab).toBe('notes')
        })

        it('preserves URL state and captures only user tab changes', () => {
            const capture = jest.spyOn(posthog, 'capture').mockImplementation()
            const searchParams = { source: 'accounts' }
            const hashParams = { view: { search: 'example' } }

            router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID, 'users'), searchParams, hashParams)

            expect(logic.values.activeTab).toBe('users')
            expect(capture).not.toHaveBeenCalledWith(AccountsEvents.TabViewed, expect.anything())

            logic.actions.setActiveTab('usage')

            expect(router.values.location.pathname).toBe(
                urls.currentProject(urls.customerAnalyticsAccount(ACCOUNT_ID, 'usage'))
            )
            expect(router.values.currentLocation.searchParams).toEqual(searchParams)
            expect(router.values.currentLocation.hashParams).toEqual(hashParams)
            expect(capture).toHaveBeenCalledWith(AccountsEvents.TabViewed, { tab: 'usage' })

            logic.actions.setActiveTab('notes')

            expect(router.values.location.pathname).toBe(urls.currentProject(urls.customerAnalyticsAccount(ACCOUNT_ID)))
            expect(router.values.currentLocation.searchParams).toEqual(searchParams)
            expect(router.values.currentLocation.hashParams).toEqual(hashParams)
        })
    })
})
