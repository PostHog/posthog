import { NodeKind } from '~/queries/schema/schema-general'

import { findSqlTableReference, sqlTableHoverContents } from './sqlTableHover'

describe('SQL table hover', () => {
    it.each([
        ['SELECT * FROM events', 'events', 'events'],
        ['SELECT * FROM events e JOIN persons p ON e.person_id = p.id', 'persons', 'persons'],
        ['SELECT * FROM `monthly totals`', 'monthly totals', 'monthly totals'],
        ['SELECT * FROM posthog.metrics', 'posthog.metrics', 'posthog.metrics'],
        ['SELECT 1; SELECT * FROM events', 'events', 'events'],
        ["SELECT '🦔' FROM events", 'events', 'events'],
        ['WITH sample AS (SELECT * FROM events) SELECT * FROM sample', 'events', 'events'],
        ["SELECT 'events' FROM persons", 'events', null],
        ['SELECT 1 -- events', 'events', null],
        ['WITH events AS (SELECT 1) SELECT * FROM events', 'events', null],
        ['WITH events AS (SELECT 1) SELECT * FROM events UNION ALL SELECT * FROM events', 'events', null],
        ['SELECT events FROM persons', 'events', null],
        ['SELECT * FROM events AS e', ' e', null],
    ])('resolves only catalog table references in %s', async (query, target, expected) => {
        const reference = await findSqlTableReference(query, query.lastIndexOf(target) + 1)
        if (expected === null) {
            expect(reference).toBeNull()
        } else {
            expect(reference?.name).toEqual(expected)
            expect(query.slice(reference!.start, reference!.end).replace(/`/g, '')).toEqual(expected)
        }
    })

    it('keeps view SQL and descriptions as code instead of active markdown', () => {
        const contents = sqlTableHoverContents({
            type: 'view',
            id: 'example-view',
            name: 'monthly_```totals',
            fields: {},
            description: '[Example](https://example.com)',
            query: { kind: NodeKind.HogQLQuery, query: "SELECT '``` [Example](https://example.com)'" },
        })

        expect(contents).toContainEqual({ value: '```plaintext\n[Example](https://example.com)\n```' })
        expect(contents).toContainEqual({ value: '**Saved view**\n\n````plaintext\nmonthly_```totals\n````' })
        expect(contents).toContainEqual({
            value: "````sql\nSELECT '``` [Example](https://example.com)'\n````",
        })
        expect(contents).toContainEqual({
            value: expect.stringMatching(/^\[Open view definition\]\(http:\/\/localhost\/.*example-view.*\)$/),
        })
    })
})
