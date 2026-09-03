import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api'

import { initKeaTests } from '~/test/init'

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
        logic = customerAnalyticsAccountSceneLogic({ accountId: ACCOUNT_ID })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
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

    it('changes the feature request composer key each time it opens', () => {
        logic.actions.openFeatureRequestComposer()
        const firstKey = logic.values.featureRequestComposerKey

        logic.actions.openFeatureRequestComposer()

        expect(logic.values.featureRequestComposerOpen).toBe(true)
        expect(logic.values.featureRequestComposerKey).toBe(firstKey + 1)
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
})
