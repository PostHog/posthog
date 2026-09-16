import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { AccountsEvents } from 'products/customer_analytics/frontend/components/Accounts/constants'
import {
    accountsByExternalIdRetrieve,
    accountsPartialUpdate,
    accountsPresenceCreate,
    accountsRetrieve,
} from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi, AccountPresenceViewerApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { scene } from './CustomerAnalyticsAccountScene'
import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'
import {
    parseExternalAccountPath,
    shouldRenderLegacyCustomerAnalyticsScene,
} from './customerAnalyticsAccountSceneUtils'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsByExternalIdRetrieve: jest.fn(),
    accountsPartialUpdate: jest.fn(),
    accountsPresenceCreate: jest.fn(),
    accountsRetrieve: jest.fn(),
}))

const mockAccountsByExternalIdRetrieve = accountsByExternalIdRetrieve as jest.MockedFunction<
    typeof accountsByExternalIdRetrieve
>
const mockAccountsPartialUpdate = accountsPartialUpdate as jest.MockedFunction<typeof accountsPartialUpdate>
const mockAccountsPresenceCreate = accountsPresenceCreate as jest.MockedFunction<typeof accountsPresenceCreate>
const mockAccountsRetrieve = accountsRetrieve as jest.MockedFunction<typeof accountsRetrieve>

const ACCOUNT_ID = '0190da51-0b0e-7000-8000-000000000001'
const PROJECT_ID = 999
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
        jest.useRealTimers()
        jest.resetAllMocks()
        mockAccountsPresenceCreate.mockResolvedValue([])
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true,
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SCENE]: true,
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS]: true,
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS]: true,
        })
        router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID))
    })

    function mountLogic(): void {
        logic = customerAnalyticsAccountSceneLogic({ accountId: ACCOUNT_ID, projectId: PROJECT_ID })
        logic.mount()
    }

    function mountExternalIdLogic(externalId: string): void {
        logic = customerAnalyticsAccountSceneLogic({ externalId, projectId: PROJECT_ID })
        logic.mount()
    }

    afterEach(() => {
        jest.useRealTimers()
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

    it('loads a UUID account while the account scene flag is disabled', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true,
        })
        mockAccountsRetrieve.mockResolvedValue(account)

        mountLogic()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockAccountsRetrieve).toHaveBeenCalledWith(String(PROJECT_ID), ACCOUNT_ID)
    })

    it('loads a UUID account before feature flags resolve', async () => {
        featureFlagLogic.unmount()
        initKeaTests()
        router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID))
        mockAccountsRetrieve.mockResolvedValue(account)
        expect(featureFlagLogic.values.receivedFeatureFlags).toBe(false)

        mountLogic()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockAccountsRetrieve).toHaveBeenCalledWith(String(PROJECT_ID), ACCOUNT_ID)
    })

    it('heartbeats account presence immediately, polls every 30 seconds, and clears it on failure', async () => {
        jest.useFakeTimers()
        const captureException = jest.spyOn(posthog, 'captureException')
        const viewers: AccountPresenceViewerApi[] = [{ user_id: 2, display_name: 'Alex Rivera' }]
        mockAccountsRetrieve.mockResolvedValue(account)
        mockAccountsPresenceCreate.mockResolvedValueOnce(viewers).mockRejectedValueOnce(new Error('Unavailable'))

        try {
            mountLogic()
            await Promise.resolve()
            await Promise.resolve()

            expect(mockAccountsPresenceCreate).toHaveBeenCalledWith(String(PROJECT_ID), ACCOUNT_ID)
            expect(logic.values.accountPresenceViewers).toEqual(viewers)

            jest.advanceTimersByTime(30_000)
            await Promise.resolve()
            await Promise.resolve()

            expect(mockAccountsPresenceCreate).toHaveBeenCalledTimes(2)
            expect(logic.values.accountPresenceViewers).toEqual([])
            expect(logic.values.accountPresenceError).toBeInstanceOf(Error)
            expect(captureException).not.toHaveBeenCalled()

            logic.unmount()
            jest.advanceTimersByTime(30_000)
            expect(mockAccountsPresenceCreate).toHaveBeenCalledTimes(2)
        } finally {
            jest.useRealTimers()
        }
    })

    it('keeps the latest presence response when an earlier request resolves later', async () => {
        const staleRequest = createDeferred<AccountPresenceViewerApi[]>()
        const latestRequest = createDeferred<AccountPresenceViewerApi[]>()
        const staleRequestStarted = createDeferred<void>()
        const latestRequestStarted = createDeferred<void>()
        const latestViewers: AccountPresenceViewerApi[] = [{ user_id: 3, display_name: 'Sam Patel' }]
        mockAccountsRetrieve.mockResolvedValue(account)
        mockAccountsPresenceCreate
            .mockImplementationOnce(() => {
                staleRequestStarted.resolve()
                return staleRequest.promise
            })
            .mockImplementationOnce(() => {
                latestRequestStarted.resolve()
                return latestRequest.promise
            })

        mountLogic()
        await staleRequestStarted.promise
        logic.actions.loadAccountPresence(ACCOUNT_ID)
        await latestRequestStarted.promise

        latestRequest.resolve(latestViewers)
        await Promise.resolve()
        await Promise.resolve()
        staleRequest.reject(new Error('Unavailable'))
        await Promise.resolve()
        await Promise.resolve()

        expect(logic.values.accountPresenceViewers).toEqual(latestViewers)
        expect(logic.values.accountPresenceError).toBeNull()
    })

    it('classifies a missing account without reporting an exception', async () => {
        const captureException = jest.spyOn(posthog, 'captureException')
        mockAccountsRetrieve.mockRejectedValue(new ApiError('Not found', 404))

        mountLogic()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isAccountMissing).toBe(true)
        expect(captureException).not.toHaveBeenCalled()
    })

    it('finishes an invalid route without loading an account', async () => {
        logic = customerAnalyticsAccountSceneLogic({ invalidRoute: true, projectId: PROJECT_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.accountLoading).toBe(false)
        expect(logic.values.isAccountMissing).toBe(true)
        expect(mockAccountsRetrieve).not.toHaveBeenCalled()
        expect(mockAccountsByExternalIdRetrieve).not.toHaveBeenCalled()
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
            expect(mockAccountsPartialUpdate).toHaveBeenCalledWith(String(PROJECT_ID), ACCOUNT_ID, {
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

    describe('external ID routes', () => {
        it('does not render the legacy scene for an external route while flags are unresolved', () => {
            expect(
                shouldRenderLegacyCustomerAnalyticsScene(
                    urls.customerAnalyticsAccountByExternalId('unresolved account'),
                    false
                )
            ).toBe(false)
            expect(shouldRenderLegacyCustomerAnalyticsScene(urls.customerAnalyticsAccount(ACCOUNT_ID), false)).toBe(
                true
            )
        })

        it.each([
            'spaces %2F slash / ? # + Unicode 漢字',
            'literal %2F sequence',
            ' leading and trailing spaces ',
            ' ',
        ])('decodes the external ID exactly once: %s', (externalId) => {
            const pathname = urls.customerAnalyticsAccountByExternalId(externalId, 'usage')

            expect(parseExternalAccountPath(pathname)).toEqual({ externalId, tab: 'usage' })
        })

        it.each([
            '/customer_analytics/accounts/by-external-id/%',
            '/customer_analytics/accounts/by-external-id/',
            '/customer_analytics/accounts/by-external-id/account/usage/extra',
        ])('rejects malformed external account paths: %s', (pathname) => {
            expect(parseExternalAccountPath(pathname)).toBeNull()
        })

        it('loads by external ID, preserves the encoded URL, and routes tabs through kea-router', async () => {
            const externalId = 'spaces %2F slash / ? # + Unicode 漢字'
            const externalUrl = urls.customerAnalyticsAccountByExternalId(externalId, 'usage')
            const searchParams = { source: 'account-link' }
            const hashParams = { view: { search: 'example' } }
            mockAccountsByExternalIdRetrieve.mockResolvedValue(account)

            router.actions.push(externalUrl, searchParams, hashParams)
            expect(
                scene.paramsToProps?.({ params: { _: externalId }, searchParams: {}, hashParams: {} })
            ).toMatchObject({ externalId })
            mountExternalIdLogic(externalId)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockAccountsByExternalIdRetrieve).toHaveBeenCalledTimes(1)
            expect(mockAccountsByExternalIdRetrieve).toHaveBeenCalledWith(String(PROJECT_ID), {
                external_id: externalId,
            })
            expect(mockAccountsRetrieve).not.toHaveBeenCalled()
            expect(mockAccountsPresenceCreate).toHaveBeenCalledWith(String(PROJECT_ID), ACCOUNT_ID)
            expect(logic.values.activeTab).toBe('usage')
            expect(router.values.location.pathname).toBe(urls.currentProject(externalUrl))

            logic.actions.setActiveTab('users')

            expect(router.values.location.pathname).toBe(
                urls.currentProject(urls.customerAnalyticsAccountByExternalId(externalId, 'users'))
            )
            expect(router.values.currentLocation.searchParams).toEqual(searchParams)
            expect(router.values.currentLocation.hashParams).toEqual(hashParams)
        })

        it('uses the resolved account ID for external account mutations', async () => {
            const externalId = 'external account'
            mockAccountsByExternalIdRetrieve.mockResolvedValue(account)
            mockAccountsPartialUpdate.mockResolvedValue({ ...account, tags: ['priority'] })

            router.actions.push(urls.customerAnalyticsAccountByExternalId(externalId))
            mountExternalIdLogic(externalId)
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.updateTags(['priority'])
            await expectLogic(logic).toFinishAllListeners()

            expect(mockAccountsPartialUpdate).toHaveBeenCalledWith(String(PROJECT_ID), ACCOUNT_ID, {
                tags: ['priority'],
            })
        })

        it('does not load an external ID when customer analytics is unavailable', async () => {
            const externalId = 'unavailable account'
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SCENE]: true,
            })

            router.actions.push(urls.customerAnalyticsAccountByExternalId(externalId))
            mountExternalIdLogic(externalId)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockAccountsByExternalIdRetrieve).not.toHaveBeenCalled()
            expect(mockAccountsPresenceCreate).not.toHaveBeenCalled()
        })

        it.each([true, false])(
            'waits for fresh flags before resolving with the detail scene enabled: %s',
            async (accountSceneEnabled) => {
                featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true })
                featureFlagLogic.unmount()
                initKeaTests()
                featureFlagLogic.mount()
                expect(featureFlagLogic.values.receivedFeatureFlags).toBe(false)
                expect(featureFlagLogic.values.featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]).toBe(true)
                const externalId = 'cached flag account'
                const externalUrl = urls.customerAnalyticsAccountByExternalId(externalId, 'usage')
                mockAccountsByExternalIdRetrieve.mockResolvedValue(account)
                router.actions.push(externalUrl)
                mountExternalIdLogic(externalId)
                await expectLogic(logic).toFinishAllListeners()

                expect(mockAccountsByExternalIdRetrieve).not.toHaveBeenCalled()

                featureFlagLogic.actions.setFeatureFlags([], {
                    [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true,
                    [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SCENE]: accountSceneEnabled,
                })
                await expectLogic(logic).toFinishAllListeners()

                expect(mockAccountsByExternalIdRetrieve).toHaveBeenCalledTimes(1)
                expect(router.values.location.pathname).toBe(
                    urls.currentProject(
                        accountSceneEnabled ? externalUrl : urls.customerAnalyticsAccount(ACCOUNT_ID, 'usage')
                    )
                )
            }
        )

        it('resolves an external account when customer analytics access arrives', async () => {
            const externalId = 'deferred external account'
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SCENE]: true,
            })
            mockAccountsByExternalIdRetrieve.mockResolvedValue(account)

            router.actions.push(urls.customerAnalyticsAccountByExternalId(externalId))
            mountExternalIdLogic(externalId)
            await expectLogic(logic).toFinishAllListeners()
            expect(mockAccountsByExternalIdRetrieve).not.toHaveBeenCalled()

            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true,
                [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SCENE]: true,
            })
            await expectLogic(logic).toFinishAllListeners()

            expect(mockAccountsByExternalIdRetrieve).toHaveBeenCalledWith(String(PROJECT_ID), {
                external_id: externalId,
            })
        })

        it('redirects to the UUID detail route only when the detail scene flag is disabled', async () => {
            const externalId = 'legacy account'
            const externalUrl = urls.customerAnalyticsAccountByExternalId(externalId, 'usage')
            const searchParams = { source: 'account-link' }
            const hashParams = { view: { search: 'example' } }
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true,
            })
            mockAccountsByExternalIdRetrieve.mockResolvedValue(account)

            router.actions.push(externalUrl, searchParams, hashParams)
            mountExternalIdLogic(externalId)
            await expectLogic(logic).toFinishAllListeners()

            expect(router.values.location.pathname).toBe(
                urls.currentProject(urls.customerAnalyticsAccount(ACCOUNT_ID, 'usage'))
            )
            expect(router.values.currentLocation.searchParams).toEqual(searchParams)
            expect(router.values.currentLocation.hashParams).toEqual(hashParams)
            expect(mockAccountsPresenceCreate).not.toHaveBeenCalled()
        })

        it('ignores an external lookup that resolves after navigation', async () => {
            const externalId = 'stale account'
            const externalUrl = urls.customerAnalyticsAccountByExternalId(externalId)
            const lookup = createDeferred<AccountApi>()
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true,
            })
            mockAccountsByExternalIdRetrieve.mockReturnValueOnce(lookup.promise)

            router.actions.push(externalUrl)
            mountExternalIdLogic(externalId)
            logic.unmount()
            router.actions.push(urls.customerAnalyticsAccounts())

            lookup.resolve(account)
            await Promise.resolve()
            await Promise.resolve()

            expect(router.values.location.pathname).toBe(urls.currentProject(urls.customerAnalyticsAccounts()))
        })
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

        it.each(['users', 'usage', 'feature_requests', 'tasks'] as const)('selects the %s tab from the URL', (tab) => {
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

            router.actions.push(urls.customerAnalyticsAccount(ACCOUNT_ID, 'tasks'))

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
