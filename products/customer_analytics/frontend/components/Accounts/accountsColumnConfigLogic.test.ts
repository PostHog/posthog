import { DatabaseSchemaTable } from '~/queries/schema/schema-general'

import { buildAccountColumnGroups } from './accountsColumnConfigLogic'
import { BILLING_CONFIRMED_MRR_COLUMN, BILLING_CREDITS_USED_COLUMN, BILLING_INVOICES_VIEW_NAME } from './constants'

const accountsTableOnly = {
    'system.accounts': { name: 'accounts', fields: {} },
} as unknown as Record<string, DatabaseSchemaTable>

const withBillingView = {
    ...accountsTableOnly,
    [BILLING_INVOICES_VIEW_NAME]: { name: BILLING_INVOICES_VIEW_NAME, fields: {} },
} as unknown as Record<string, DatabaseSchemaTable>

describe('buildAccountColumnGroups', () => {
    it('adds the Billing group when the billing view is present in the schema', () => {
        const billing = buildAccountColumnGroups(withBillingView, []).find((group) => group.key === 'billing')
        expect(billing?.label).toBe('Billing')
        expect(billing?.options.map((option) => option.name)).toEqual([
            BILLING_CONFIRMED_MRR_COLUMN,
            BILLING_CREDITS_USED_COLUMN,
        ])
    })

    it('omits the Billing group when the billing view is absent', () => {
        const groups = buildAccountColumnGroups(accountsTableOnly, [])
        expect(groups.find((group) => group.key === 'billing')).toBeUndefined()
    })

    it('uses bare-name expressions so the backend special-cases them (not join-prefixed)', () => {
        const billing = buildAccountColumnGroups(withBillingView, []).find((group) => group.key === 'billing')
        expect(billing?.options).toHaveLength(2)
        for (const option of billing?.options ?? []) {
            expect(option.expression).toBe(option.name)
        }
    })
})
