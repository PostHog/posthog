import { NodeKind } from '~/queries/schema/schema-general'

import { createAccountSqlQueryNode } from './accountSqlQuery'

describe('createAccountSqlQueryNode', () => {
    it('passes the account external ID as the placeholder value', () => {
        const query = 'select * from invented_table where org_id = {account_external_id}'
        expect(createAccountSqlQueryNode(query, 'org-123')?.source).toMatchObject({
            kind: NodeKind.HogQLQuery,
            query,
            values: { account_external_id: 'org-123' },
        })
    })

    it.each([
        ['an unscoped query', 'select * from invented_table', 'org-123'],
        ['a blank query', '  ', 'org-123'],
        ['an account without an external ID', 'select {account_external_id}', ' '],
    ])('returns no query for %s', (_, query, externalId) => {
        expect(createAccountSqlQueryNode(query, externalId)).toBeNull()
    })
})
