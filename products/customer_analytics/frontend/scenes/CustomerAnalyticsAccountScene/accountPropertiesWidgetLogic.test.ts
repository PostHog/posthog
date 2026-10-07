import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { teamLogic } from 'scenes/teamLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import { accountsPartialUpdate, accountsRetrieve } from '../../generated/api'
import type { AccountApi } from '../../generated/api.schemas'
import { accountPropertiesWidgetLogic } from './accountPropertiesWidgetLogic'
import { accountPropertyUpdatesLogic } from './accountPropertyUpdatesLogic'

jest.mock('lib/utils/accessControlUtils', () => ({ userHasAccess: jest.fn(() => true) }))
jest.mock('../../generated/api', () => ({
    ...jest.requireActual('../../generated/api'),
    accountsRetrieve: jest.fn(),
    accountsPartialUpdate: jest.fn(),
}))

const PROJECT_ID = MOCK_DEFAULT_TEAM.id
const ACCOUNT_ID = '11111111-1111-4111-8111-111111111111'
const initialAccount: AccountApi = {
    id: ACCOUNT_ID,
    name: 'Example account',
    external_id: 'example-account',
    notebooks: [],
    ignored_at: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: null,
    properties: {
        billing_id: 'billing-example',
        website_domain: 'example.com',
        slack_channel_id: 'CEXAMPLE',
        usage_dashboard_link: 'https://example.com/usage',
    },
}
const mockRetrieve = jest.mocked(accountsRetrieve)
const mockUpdate = jest.mocked(accountsPartialUpdate)

describe('accountPropertiesWidgetLogic', () => {
    let account: AccountApi
    const mounted: ReturnType<typeof accountPropertiesWidgetLogic.build>[] = []
    const mount = async (instanceId: string): Promise<ReturnType<typeof accountPropertiesWidgetLogic.build>> => {
        const logic = accountPropertiesWidgetLogic({
            projectId: PROJECT_ID,
            accountId: ACCOUNT_ID,
            instanceId,
            initialConfig: {
                properties: [
                    { kind: 'account', key: 'website_domain' },
                    { kind: 'account', key: 'billing_id' },
                    { kind: 'account', key: 'email_domains' },
                    { kind: 'account', key: 'known_emails' },
                    { kind: 'account', key: 'stripe_customer_id' },
                ],
            },
        })
        logic.mount()
        mounted.push(logic)
        await waitFor(() => expect(logic.values.account).not.toBeNull())
        return logic
    }

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        jest.mocked(userHasAccess).mockReturnValue(true)
        account = structuredClone(initialAccount)
        mockRetrieve.mockImplementation(async () => structuredClone(account))
        mockUpdate.mockImplementation(async (_, __, patch) => {
            account = { ...account, properties: patch?.properties ?? account.properties }
            return account
        })
    })
    afterEach(() => {
        mounted.splice(0).forEach((logic) => logic.unmount())
        resumeKeaLoadersErrors()
    })

    it('retains failed input, blocks duplicate saves and refreshes other instances without replacing their drafts', async () => {
        silenceKeaLoadersErrors()
        const first = await mount('first')
        const second = await mount('second')
        first.actions.editNativeProperty('website_domain')
        first.actions.setNativeDraft('new.example.com')
        second.actions.editNativeProperty('billing_id')
        second.actions.setNativeDraft('unsaved-billing')
        account = { ...account, properties: { ...account.properties, slack_channel_id: 'CCONCURRENT' } }
        mockUpdate.mockRejectedValueOnce(new Error('Save failed'))
        await expectLogic(first, () => {
            first.actions.saveNativeProperty()
            first.actions.saveNativeProperty()
        }).toFinishAllListeners()
        expect(mockUpdate).toHaveBeenCalledTimes(1)
        expect(first.values).toMatchObject({
            nativeSaveFailed: true,
            nativeEditingKey: 'website_domain',
            nativeDraft: 'new.example.com',
        })
        expect(second.values).toMatchObject({ nativeEditingKey: 'billing_id', nativeDraft: 'unsaved-billing' })
        await expectLogic(first, () => first.actions.saveNativeProperty()).toFinishAllListeners()
        expect(mockUpdate).toHaveBeenLastCalledWith(String(PROJECT_ID), ACCOUNT_ID, {
            properties: {
                ...initialAccount.properties,
                website_domain: 'new.example.com',
                slack_channel_id: 'CCONCURRENT',
            },
        })
        expect(first.values.nativeEditingKey).toBeNull()
        expect(second.values.account?.properties?.website_domain).toBe('new.example.com')
        expect(second.values.nativeDraft).toBe('unsaved-billing')
    })

    it('serializes two widget saves so each fresh merge keeps the other changed field', async () => {
        const first = await mount('first')
        const second = await mount('second')
        let releaseWrite!: () => void
        const pendingWrite = new Promise<void>((resolve) => {
            releaseWrite = resolve
        })
        mockUpdate.mockImplementationOnce(async (_, __, patch) => {
            await pendingWrite
            account = { ...account, properties: patch?.properties ?? account.properties }
            return account
        })
        first.actions.editNativeProperty('website_domain')
        first.actions.setNativeDraft('saved.example.com')
        second.actions.editNativeProperty('billing_id')
        second.actions.setNativeDraft('saved-billing')
        first.actions.saveNativeProperty()
        second.actions.saveNativeProperty()
        try {
            await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1))
        } finally {
            releaseWrite()
        }
        await expectLogic(first).toFinishAllListeners()
        expect(mockUpdate).toHaveBeenCalledTimes(2)
        expect(account.properties).toMatchObject({
            website_domain: 'saved.example.com',
            billing_id: 'saved-billing',
            slack_channel_id: 'CEXAMPLE',
        })
        expect(first.values.account).toEqual(account)
        expect(second.values.account).toEqual(account)
    })

    it.each([
        ['email_domains', [' @EXAMPLE.COM ', 'example.com', 'other.example.com'], ['example.com', 'other.example.com']],
        ['known_emails', [' Person@EXAMPLE.COM ', 'person@example.com'], ['person@example.com']],
    ] as const)('uses the account modal normalization for %s', async (propertyKey, input, expected) => {
        const logic = await mount('first')
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Admin,
        })
        logic.actions.editNativeProperty(propertyKey)
        logic.actions.setNativeDraft([...input])
        await expectLogic(logic, () => logic.actions.saveNativeProperty()).toFinishAllListeners()
        expect(account.properties?.[propertyKey]).toEqual(expected)
        expect(account.properties?.usage_dashboard_link).toBe(initialAccount.properties?.usage_dashboard_link)
    })

    it.each([
        { propertyKey: 'website_domain' as const, editor: false, level: OrganizationMembershipLevel.Admin },
        { propertyKey: 'email_domains' as const, editor: true, level: OrganizationMembershipLevel.Member },
        { propertyKey: 'known_emails' as const, editor: true, level: OrganizationMembershipLevel.Member },
        { propertyKey: 'stripe_customer_id' as const, editor: true, level: OrganizationMembershipLevel.Admin },
    ])(
        'blocks a restricted native write for $propertyKey (editor: $editor, level: $level)',
        async ({ propertyKey, editor, level }) => {
            jest.mocked(userHasAccess).mockReturnValue(editor)
            const logic = await mount('first')
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, effective_membership_level: level })
            logic.actions.editNativeProperty(propertyKey)
            logic.actions.setNativeDraft(
                propertyKey === 'email_domains' || propertyKey === 'known_emails' ? ['example.com'] : 'blocked'
            )
            await expectLogic(logic, () => logic.actions.saveNativeProperty()).toFinishAllListeners()
            expect(mockUpdate).not.toHaveBeenCalled()
        }
    )

    it('distinguishes an initial load failure from missing values and recovers on retry', async () => {
        silenceKeaLoadersErrors()
        mockRetrieve.mockRejectedValueOnce(new Error('Account unavailable'))
        const logic = accountPropertiesWidgetLogic({
            projectId: PROJECT_ID,
            accountId: ACCOUNT_ID,
            instanceId: 'first',
        })
        logic.mount()
        mounted.push(logic)
        await waitFor(() => expect(logic.values.accountLoadFailed).toBe(true))
        expect(logic.values.account).toBeNull()
        logic.actions.loadAccount()
        await waitFor(() => expect(logic.values.account).toEqual(initialAccount))
        expect(logic.values.accountLoadFailed).toBe(false)
    })

    it('does not let an earlier account read replace a value saved by another visible editor', async () => {
        let resolveRead!: (account: AccountApi) => void
        const read = new Promise<AccountApi>((resolve) => {
            resolveRead = resolve
        })
        mockRetrieve.mockReturnValueOnce(read)
        const logic = accountPropertiesWidgetLogic({
            projectId: PROJECT_ID,
            accountId: ACCOUNT_ID,
            instanceId: 'first',
        })
        logic.mount()
        mounted.push(logic)
        await waitFor(() => expect(mockRetrieve).toHaveBeenCalledTimes(1))
        const saved = {
            ...initialAccount,
            properties: { ...initialAccount.properties, website_domain: 'saved.example.com' },
        }
        accountPropertyUpdatesLogic.actions.accountUpdated(PROJECT_ID, saved)
        resolveRead(initialAccount)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.account?.properties?.website_domain).toBe('saved.example.com')
    })

    it('does not accept updates for another project or account', async () => {
        const logic = await mount('first')
        accountPropertyUpdatesLogic.actions.accountUpdated(PROJECT_ID + 1, { ...account, name: 'Other project' })
        accountPropertyUpdatesLogic.actions.accountUpdated(PROJECT_ID, {
            ...account,
            id: 'other-account',
            name: 'Other account',
        })
        expect(logic.values.account?.name).toBe(initialAccount.name)
    })
})
