import { NodeKind } from '~/queries/schema/schema-general'

import { createAccountSqlQueryNode, getAccountSqlQueryConfigError } from './accountSqlQuery'
import cases from './accountSqlQuery.test.json'

describe('createAccountSqlQueryNode', () => {
    it.each(
        cases.filter(({ name }) =>
            ['system accounts external ID', 'comment placeholder', 'string placeholder'].includes(name)
        )
    )('validates the editor config for $name with the parsed filter', async ({ query, valid }) => {
        expect(await getAccountSqlQueryConfigError({ query })).toEqual(valid ? undefined : expect.any(String))
    })
    it.each(cases.filter(({ valid }) => valid))('runs $name with the current account value', async ({ query }) => {
        expect((await createAccountSqlQueryNode(query, "org-'123"))?.source).toMatchObject({
            kind: NodeKind.HogQLQuery,
            query,
            values: { account_external_id: "org-'123" },
        })
    })

    it.each([
        ...cases.filter(({ valid }) => !valid).map(({ name, query }) => [name, query, 'org-123']),
        ['a blank query', '  ', 'org-123'],
        ['an account without an external ID', 'select {account_external_id}', ' '],
        ['invalid SQL', 'select * from engagements where', 'org-123'],
    ])('returns no query for %s', async (_, query, externalId) => {
        expect(await createAccountSqlQueryNode(query, externalId)).toBeNull()
    })
})
