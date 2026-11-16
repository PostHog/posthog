import { urls } from 'scenes/urls'

import { joinKeyCheckQuery } from './biJoinKeyCheck'

it('opens a full-table check for repeated and null nested keys as an editable SQL draft', () => {
    const query = joinKeyCheckQuery({
        id: 'example',
        joining_table_name: 'example_accounts',
        joining_table_key: 'properties.account_id',
    })!
    const url = new URL(urls.sqlEditor({ query }), 'https://example.com')
    expect(url.searchParams.get('open_query')).toBe(query)
    expect(query).toContain('SELECT properties.account_id AS join_key\n    FROM example_accounts')
    expect(query).toContain('HAVING count(*) > 1 OR isNull(join_key)')
    expect(query).toContain('LIMIT 100')
})

it('quotes table names and refuses expression keys instead of checking a different key', () => {
    expect(
        joinKeyCheckQuery({ id: 'example', joining_table_name: 'example orders', joining_table_key: 'id' })
    ).toContain('FROM "example orders"')
    for (const key of [
        '"Account ID"',
        'properties."account-id"',
        '"account.id"',
        '`Account ID`',
        '"account""id"',
        '"account\\"id"',
    ]) {
        expect(
            joinKeyCheckQuery({ id: 'example', joining_table_name: 'example_accounts', joining_table_key: key })
        ).toContain(`SELECT ${key} AS join_key`)
    }
    for (const key of ['lower(email)', '"id', '"id"; SELECT 1', 'id -- comment', 'id + 1']) {
        expect(
            joinKeyCheckQuery({ id: 'example', joining_table_name: 'example_accounts', joining_table_key: key })
        ).toBeNull()
    }
    expect(joinKeyCheckQuery({ id: 'example', joining_table_name: 'example_accounts' })).toBeNull()
})
