import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountPropertyDataLogic } from '../../scenes/CustomerAnalyticsAccountScene/accountPropertyDataLogic'
import { accountPropertyUpdatesLogic } from '../../scenes/CustomerAnalyticsAccountScene/accountPropertyUpdatesLogic'
import { accountLinksLogic } from './accountLinksLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    // Keep the real module for everything else — connected logics (e.g. column config's
    // customPropertyDefinitionsList) call other generated functions on mount, and an
    // absent export makes their loaders throw on every test.
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsRetrieve: jest.fn(),
}))

const mockAccountsRetrieve = accountsRetrieve as jest.MockedFunction<typeof accountsRetrieve>

const buildAccount = (overrides: Partial<AccountApi> = {}): AccountApi => ({
    id: 'acc-1',
    name: 'Acme',
    external_id: 'ext-1',
    properties: {
        hubspot_deal_id: 'deal-1',
        billing_id: 'cus_123',
    },
    tags: [],
    notebooks: [],
    ignored_at: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
})

describe('accountLinksLogic', () => {
    let logic: ReturnType<typeof accountLinksLogic.build>
    let shared: ReturnType<typeof accountPropertyDataLogic.build>

    const mountWith = async (initial: AccountApi): Promise<void> => {
        mockAccountsRetrieve.mockResolvedValue(initial)
        logic = accountLinksLogic({ accountId: 'acc-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        shared = accountPropertyDataLogic({ projectId: MOCK_DEFAULT_TEAM.id, accountId: 'acc-1' })
        shared.mount()
    })

    afterEach(() => {
        logic?.unmount()
        shared.unmount()
    })

    it.each(['initial', 'refresh'])('keeps a widget save when a stale %s read finishes', async (phase) => {
        const initial = buildAccount()
        if (phase === 'refresh') {
            await mountWith(initial)
        }
        mockAccountsRetrieve.mockClear()
        let resolveRead!: (value: AccountApi) => void
        mockAccountsRetrieve.mockReturnValueOnce(new Promise<AccountApi>((resolve) => (resolveRead = resolve)))
        if (phase === 'initial') {
            logic = accountLinksLogic({ accountId: initial.id })
            logic.mount()
        } else {
            logic.actions.loadAccount()
        }
        const saved = buildAccount({ properties: { billing_id: 'saved-billing' } })
        try {
            await waitFor(() => expect(mockAccountsRetrieve).toHaveBeenCalledTimes(1))
            accountPropertyUpdatesLogic.actions.accountUpdated(MOCK_DEFAULT_TEAM.id, saved)
            resolveRead(initial)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.currentFieldValues.billing_id).toBe('saved-billing')
            expect(shared.values.account).toEqual(saved)
        } finally {
            resolveRead(initial)
            await expectLogic(logic).toFinishAllListeners()
        }
    })

})
