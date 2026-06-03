import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { accountsPartialUpdate, accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountLinksLogic } from './accountLinksLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    accountsRetrieve: jest.fn(),
    accountsPartialUpdate: jest.fn(),
}))

const mockAccountsRetrieve = accountsRetrieve as jest.MockedFunction<typeof accountsRetrieve>
const mockAccountsPartialUpdate = accountsPartialUpdate as jest.MockedFunction<typeof accountsPartialUpdate>

const TEAM = String(MOCK_DEFAULT_TEAM.id)

const buildAccount = (overrides: Partial<AccountApi> = {}): AccountApi => ({
    id: 'acc-1',
    name: 'Acme',
    external_id: 'ext-1',
    properties: {
        csm: { id: 1, email: 'csm@example.com' },
        billing_id: 'cus_123',
    },
    tags: [],
    notebooks: [],
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
})

const linkByKey = (
    logic: ReturnType<typeof accountLinksLogic.build>,
    key: string
): ReturnType<typeof accountLinksLogic.build>['values']['links'][number] | undefined =>
    logic.values.links.find((l) => l.key === key)

describe('accountLinksLogic', () => {
    let logic: ReturnType<typeof accountLinksLogic.build>

    const mountWith = async (initial: AccountApi): Promise<void> => {
        mockAccountsRetrieve.mockResolvedValue(initial)
        logic = accountLinksLogic({ accountId: 'acc-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('spreads existing properties when setting a property field, without clobbering siblings', async () => {
        await mountWith(
            buildAccount({
                properties: { csm: { id: 1, email: 'csm@example.com' }, billing_id: null },
            })
        )
        const updated = buildAccount({
            properties: { csm: { id: 1, email: 'csm@example.com' }, billing_id: null, slack_channel_id: 'C999' },
        })
        mockAccountsPartialUpdate.mockResolvedValue(updated)

        logic.actions.updateAccountField('slack_channel_id', 'C999')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockAccountsPartialUpdate).toHaveBeenCalledWith(TEAM, 'acc-1', {
            properties: { csm: { id: 1, email: 'csm@example.com' }, billing_id: null, slack_channel_id: 'C999' },
        })
        expect(logic.values.account).toEqual(updated)
        expect(linkByKey(logic, 'slack')?.disabledReason).toBeNull()
        expect(linkByKey(logic, 'slack')?.configField).toBeNull()
    })

    it('trims the value before saving', async () => {
        await mountWith(buildAccount({ properties: { csm: { id: 1, email: 'csm@example.com' }, billing_id: null } }))
        mockAccountsPartialUpdate.mockResolvedValue(buildAccount({ properties: { billing_id: 'cus_new' } }))

        logic.actions.updateAccountField('billing_id', '  cus_new  ')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockAccountsPartialUpdate).toHaveBeenCalledWith(TEAM, 'acc-1', {
            properties: { csm: { id: 1, email: 'csm@example.com' }, billing_id: 'cus_new' },
        })
    })

    it('sends external_id as a top-level field with no properties key', async () => {
        await mountWith(buildAccount({ external_id: null }))
        mockAccountsPartialUpdate.mockResolvedValue(buildAccount({ external_id: 'ext-9' }))

        logic.actions.updateAccountField('external_id', 'ext-9')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockAccountsPartialUpdate).toHaveBeenCalledWith(TEAM, 'acc-1', { external_id: 'ext-9' })
        expect(linkByKey(logic, 'organization')?.disabledReason).toBeNull()
        expect(linkByKey(logic, 'revenue')?.disabledReason).toBeNull()
    })

    it('does nothing for an empty value', async () => {
        await mountWith(buildAccount({ properties: { slack_channel_id: null } }))

        logic.actions.updateAccountField('slack_channel_id', '   ')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockAccountsPartialUpdate).not.toHaveBeenCalled()
    })

    it('flips isFieldSaving during the in-flight window', async () => {
        await mountWith(buildAccount({ properties: { billing_id: null } }))
        let resolveUpdate!: (value: AccountApi) => void
        mockAccountsPartialUpdate.mockReturnValueOnce(
            new Promise<AccountApi>((resolve) => {
                resolveUpdate = resolve
            })
        )

        logic.actions.updateAccountField('billing_id', 'cus_new')
        await new Promise<void>((r) => setTimeout(r, 0))
        expect(logic.values.isFieldSaving('billing_id')).toBe(true)

        resolveUpdate(buildAccount({ properties: { billing_id: 'cus_new' } }))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.isFieldSaving('billing_id')).toBe(false)
    })

    it('is a no-op while a save for the same field is already in flight', async () => {
        await mountWith(buildAccount({ properties: { billing_id: null } }))
        let resolveFirst!: (value: AccountApi) => void
        mockAccountsPartialUpdate.mockReturnValueOnce(
            new Promise<AccountApi>((resolve) => {
                resolveFirst = resolve
            })
        )

        logic.actions.updateAccountField('billing_id', 'a')
        await new Promise<void>((r) => setTimeout(r, 0))
        logic.actions.updateAccountField('billing_id', 'b')
        await new Promise<void>((r) => setTimeout(r, 0))

        expect(mockAccountsPartialUpdate).toHaveBeenCalledTimes(1)

        resolveFirst(buildAccount())
        await expectLogic(logic).toFinishAllListeners()
    })

    it('leaves the link disabled on failure', async () => {
        await mountWith(buildAccount({ properties: { slack_channel_id: null } }))
        mockAccountsPartialUpdate.mockRejectedValueOnce(new Error('boom'))

        logic.actions.updateAccountField('slack_channel_id', 'C1')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isFieldSaving('slack_channel_id')).toBe(false)
        expect(linkByKey(logic, 'slack')?.disabledReason).toBe('No Slack channel set')
        expect(linkByKey(logic, 'slack')?.configField).not.toBeNull()
    })
})
