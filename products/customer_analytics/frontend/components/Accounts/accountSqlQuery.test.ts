import { NodeKind } from '~/queries/schema/schema-general'

import { createAccountSqlQueryNode, getAccountSqlQueryConfigError } from './accountSqlQuery'
import cases from './accountSqlQuery.test.json'

describe('createAccountSqlQueryNode', () => {
    const connectionId = '11111111-1111-4111-8111-111111111111'
    const scopedQuery = 'select * from example_engagements where org_id = {account_external_id}'

    it.each([undefined, connectionId])('keeps the selected source and binds each account for %s', async (sourceId) => {
        for (const externalId of ['example-org-one', "example-org-'two"]) {
            const node = await createAccountSqlQueryNode(scopedQuery, externalId, sourceId)
            expect(node?.source).toEqual({
                kind: NodeKind.HogQLQuery,
                query: scopedQuery,
                ...(sourceId ? { connectionId: sourceId } : {}),
                values: { account_external_id: externalId },
                tags: expect.any(Object),
            })
            expect(await getAccountSqlQueryConfigError({ query: scopedQuery, connectionId: sourceId })).toBeUndefined()
        }
    })

    it.each([null, false, 123, '', 'not-a-connection', [], { id: connectionId }].map((sourceId) => ({ sourceId })))(
        'blocks an invalid saved connection $sourceId without falling back to the warehouse',
        async ({ sourceId }) => {
            expect(await getAccountSqlQueryConfigError({ query: scopedQuery, connectionId: sourceId })).toContain(
                'invalid connection'
            )
            expect(await createAccountSqlQueryNode(scopedQuery, 'example-org', sourceId)).toBeNull()
        }
    )

    it.each(cases)('validates the editor config for $name with the parsed filter', async ({ query, valid }) => {
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
