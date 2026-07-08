import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { accountsPartialUpdate, accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountLinksLogic } from './accountLinksLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    // Keep the real module for everything else — connected logics (e.g. column config's
    // customPropertyDefinitionsList) call other generated functions on mount, and an
    // absent export makes their loaders throw on every test.
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
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

    it('openEditor pre-fills the form from the current account', async () => {
        await mountWith(
            buildAccount({ external_id: 'ext-1', properties: { billing_id: 'cus_1', slack_channel_id: 'C1' } })
        )
        logic.actions.openEditor()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.editorOpen).toBe(true)
        expect(logic.values.formValues).toEqual({
            external_id: 'ext-1',
            billing_id: 'cus_1',
            slack_channel_id: 'C1',
            usage_dashboard_link: '',
            sfdc_id: '',
        })
    })

    it('saveLinks PATCHes external_id top-level and spreads properties without clobbering', async () => {
        await mountWith(
            buildAccount({
                external_id: 'ext-1',
                properties: { csm: { id: 1, email: 'csm@example.com' }, billing_id: 'old' },
            })
        )
        const updated = buildAccount({ external_id: 'ext-2' })
        mockAccountsPartialUpdate.mockResolvedValue(updated)

        logic.actions.openEditor()
        logic.actions.setFormValues({
            external_id: 'ext-2',
            billing_id: 'new',
            slack_channel_id: 'C9',
            usage_dashboard_link: '',
            sfdc_id: '001abc',
        })
        logic.actions.saveLinks()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockAccountsPartialUpdate).toHaveBeenCalledWith(TEAM, 'acc-1', {
            external_id: 'ext-2',
            properties: {
                csm: { id: 1, email: 'csm@example.com' },
                billing_id: 'new',
                slack_channel_id: 'C9',
                usage_dashboard_link: null,
                sfdc_id: '001abc',
            },
        })
        expect(logic.values.account).toEqual(updated)
        expect(logic.values.editorOpen).toBe(false)
    })

    it('saveLinks sends null for empty or whitespace fields', async () => {
        await mountWith(buildAccount({ external_id: 'ext-1', properties: { billing_id: 'b' } }))
        mockAccountsPartialUpdate.mockResolvedValue(buildAccount())

        logic.actions.setFormValues({
            external_id: '',
            billing_id: '',
            slack_channel_id: '   ',
            usage_dashboard_link: '',
            sfdc_id: '',
        })
        logic.actions.saveLinks()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockAccountsPartialUpdate).toHaveBeenCalledWith(TEAM, 'acc-1', {
            external_id: null,
            properties: { billing_id: null, slack_channel_id: null, usage_dashboard_link: null, sfdc_id: null },
        })
    })

    it('flips savingLinks during the in-flight window', async () => {
        await mountWith(buildAccount())
        let resolveUpdate!: (value: AccountApi) => void
        mockAccountsPartialUpdate.mockReturnValueOnce(
            new Promise<AccountApi>((resolve) => {
                resolveUpdate = resolve
            })
        )

        logic.actions.saveLinks()
        await new Promise<void>((r) => setTimeout(r, 0))
        expect(logic.values.savingLinks).toBe(true)

        resolveUpdate(buildAccount())
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.savingLinks).toBe(false)
    })

    it('is a no-op while a save is already in flight', async () => {
        await mountWith(buildAccount())
        let resolveFirst!: (value: AccountApi) => void
        mockAccountsPartialUpdate.mockReturnValueOnce(
            new Promise<AccountApi>((resolve) => {
                resolveFirst = resolve
            })
        )

        logic.actions.saveLinks()
        await new Promise<void>((r) => setTimeout(r, 0))
        logic.actions.saveLinks()
        await new Promise<void>((r) => setTimeout(r, 0))

        expect(mockAccountsPartialUpdate).toHaveBeenCalledTimes(1)
        resolveFirst(buildAccount())
        await expectLogic(logic).toFinishAllListeners()
    })

    it('keeps the editor open and account unchanged on failure', async () => {
        const initial = buildAccount({ external_id: 'ext-1' })
        await mountWith(initial)
        mockAccountsPartialUpdate.mockRejectedValueOnce(new Error('boom'))

        logic.actions.openEditor()
        logic.actions.saveLinks()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.editorOpen).toBe(true)
        expect(logic.values.savingLinks).toBe(false)
        expect(logic.values.account).toEqual(initial)
    })

    it('organization link opens the group and carries the accounts list as backUrl', async () => {
        router.actions.push('/customer_analytics/accounts', {}, { view: { search: 'acme' } })
        await mountWith(buildAccount({ external_id: 'ext-1' }))

        const organization = logic.values.links.find((link) => link.key === 'organization')
        const destination = combineUrl(organization!.to!)
        expect(destination.pathname).toBe('/groups/0/ext-1')
        expect(destination.searchParams.backName).toBe('Accounts')
        expect(destination.searchParams.backUrl).toContain('/customer_analytics/accounts')
        expect(destination.searchParams.backUrl).toContain('#view=')
    })

    it('organization link is disabled without an external_id', async () => {
        await mountWith(buildAccount({ external_id: null }))

        const organization = logic.values.links.find((link) => link.key === 'organization')
        expect(organization?.to).toBeNull()
        expect(organization?.disabledReason).toBe('No external ID set')
    })
})
