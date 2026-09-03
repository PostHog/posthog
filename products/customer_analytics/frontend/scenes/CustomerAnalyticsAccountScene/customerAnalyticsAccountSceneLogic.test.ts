import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { AccountsEvents } from 'products/customer_analytics/frontend/components/Accounts/constants'
import { accountsPartialUpdate, accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsPartialUpdate: jest.fn(),
    accountsRetrieve: jest.fn(),
}))

const mockAccountsPartialUpdate = accountsPartialUpdate as jest.MockedFunction<typeof accountsPartialUpdate>
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

interface Deferred<T> {
    promise: Promise<T>
    resolve: (value: T) => void
    reject: (reason: unknown) => void
}

function createDeferred<T>(): Deferred<T> {
    let resolve!: (value: T) => void
    let reject!: (reason: unknown) => void
    const promise = new Promise<T>((promiseResolve, promiseReject) => {
        resolve = promiseResolve
        reject = promiseReject
    })
    return { promise, resolve, reject }
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
    })

    function mountLogic(): void {
        logic = customerAnalyticsAccountSceneLogic({ accountId: ACCOUNT_ID })
        logic.mount()
    }

    afterEach(() => {
        logic.unmount()
        featureFlagLogic.unmount()
    })

    it('loads the account on mount and uses its name in the breadcrumb', async () => {
        mockAccountsRetrieve.mockResolvedValue(account)

        mountLogic()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.account).toEqual(account)
        expect(logic.values.accountLoadError).toBeNull()
        expect(logic.values.breadcrumbs.at(-1)?.name).toBe(account.name)
    })

    it('classifies a missing account without reporting an exception', async () => {
        const captureException = jest.spyOn(posthog, 'captureException')
        mockAccountsRetrieve.mockRejectedValue(new ApiError('Not found', 404))

        mountLogic()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isAccountMissing).toBe(true)
        expect(captureException).not.toHaveBeenCalled()
    })

    it('reports unexpected load failures', async () => {
        const failure = new ApiError('Server error', 500)
        const captureException = jest.spyOn(posthog, 'captureException')
        mockAccountsRetrieve.mockRejectedValue(failure)

        mountLogic()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isAccountMissing).toBe(false)
        expect(logic.values.accountLoadError).toBe(failure)
        expect(captureException).toHaveBeenCalledWith(failure, {
            scope: 'customerAnalyticsAccountSceneLogic.loadAccount',
        })
    })

    it('clears a previous error when retrying', async () => {
        mockAccountsRetrieve.mockRejectedValueOnce(new ApiError('Server error', 500))

        mountLogic()
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

    describe('tag updates', () => {
        beforeEach(async () => {
            mockAccountsRetrieve.mockResolvedValue(account)
            mountLogic()
            await expectLogic(logic).toFinishAllListeners()
            mockAccountsRetrieve.mockClear()
        })

        it('saves tags and keeps the optimistic value', async () => {
            const updatedAccount = { ...account, tags: ['priority'] }
            const capture = jest.spyOn(posthog, 'capture').mockImplementation()
            mockAccountsPartialUpdate.mockResolvedValue(updatedAccount)

            logic.actions.updateTags(['priority'])

            expect(logic.values.account?.tags).toEqual(['priority'])
            expect(logic.values.tagsSaving).toBe(true)
            await expectLogic(logic).toFinishAllListeners()
            expect(mockAccountsPartialUpdate).toHaveBeenCalledWith(String(logic.values.currentTeamId), ACCOUNT_ID, {
                tags: ['priority'],
            })
            expect(logic.values.account).toEqual(updatedAccount)
            expect(logic.values.tagsSaving).toBe(false)
            expect(capture).toHaveBeenCalledWith(AccountsEvents.TagsUpdated, { tag_count: 1 })
        })

        it('restores the account when saving tags fails', async () => {
            const failure = new ApiError('Server error', 500)
            mockAccountsPartialUpdate.mockRejectedValue(failure)
            mockAccountsRetrieve.mockResolvedValue(account)

            logic.actions.updateTags(['priority'])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.account).toEqual(account)
            expect(logic.values.tagsSaving).toBe(false)
            expect(mockAccountsRetrieve).toHaveBeenCalled()
        })

        it.each(['success', 'failure'] as const)(
            'keeps the latest tags when an earlier save ends with %s',
            async (staleResult) => {
                const staleRequest = createDeferred<AccountApi>()
                const latestRequest = createDeferred<AccountApi>()
                const staleRequestStarted = createDeferred<void>()
                const latestRequestStarted = createDeferred<void>()
                const latestAccount = { ...account, tags: ['latest'] }
                mockAccountsPartialUpdate
                    .mockImplementationOnce(() => {
                        staleRequestStarted.resolve()
                        return staleRequest.promise
                    })
                    .mockImplementationOnce(() => {
                        latestRequestStarted.resolve()
                        return latestRequest.promise
                    })

                logic.actions.updateTags(['stale'])
                await staleRequestStarted.promise
                logic.actions.updateTags(['latest'])
                await latestRequestStarted.promise

                latestRequest.resolve(latestAccount)
                if (staleResult === 'success') {
                    staleRequest.resolve({ ...account, tags: ['stale'] })
                } else {
                    staleRequest.reject(new ApiError('Server error', 500))
                }
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.account).toEqual(latestAccount)
                expect(logic.values.tagsSaving).toBe(false)
                expect(mockAccountsRetrieve).not.toHaveBeenCalled()
            }
        )
    })

    describe('tab routing', () => {
        beforeEach(async () => {
            mockAccountsRetrieve.mockResolvedValue(account)
            mountLogic()
            await expectLogic(logic).toFinishAllListeners()
        })

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
