import { renderColumnMeta } from '~/queries/nodes/DataTable/renderColumnMeta'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

describe('renderColumnMeta', () => {
    const hogQLQuery: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
    }
    const eventsQuery: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: { kind: NodeKind.EventsQuery, select: [] },
    }

    // When the response is absent or the query errored the DataTable falls back to the raw select
    // expressions as column keys. The header must read as a label, not internal query text.
    it.each([
        ['ACCOUNTS.TAGS.NAMES AS TAG_NAMES', 'TAG_NAMES'],
        ['count() -- Total events', 'Total events'],
        ['`resolved col`', 'resolved col'],
        ['plain_resolved_name', 'plain_resolved_name'],
        // A `--` inside a string literal must stay intact, not be split as a comment
        ["replaceAll(url, '--', '')", "replaceAll(url, '--', '')"],
    ])('HogQL key %p renders header %p', (key, expected) => {
        expect(renderColumnMeta(key, hogQLQuery).title).toEqual(expected)
    })

    // A non-HogQL select expression with an `AS alias` resolves to the alias name once the response
    // lands. The header must show that alias during load too — including `properties.`/`person.properties.`
    // columns, which hit the property branches and used to render the raw `… AS …` expression.
    it.each([
        ['toString(properties.x) AS renamed', 'renamed'],
        ['properties.$browser AS Browser', 'Browser'],
        ['properties.plan_tier AS "Plan tier"', 'Plan tier'],
        ['person.properties.email AS Email', 'Email'],
    ])('non-HogQL select key %p renders alias %p', (key, expected) => {
        expect(renderColumnMeta(key, eventsQuery).title).toEqual(expected)
    })
})
