import { splitQueries } from 'lib/monaco/multiQueryUtils'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import * as parserWorker from 'scenes/data-warehouse/editor/hogqlParserWorkerManager'

import { DatabaseSchemaTable, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { findSqlCatalogTable, findSqlTableReference, sqlTableHoverContents } from './sqlTableHover'

describe('SQL table hover', () => {
    beforeEach(() => initKeaTests(false))

    it.each([
        ['SELECT * FROM events', 'events', 'events'],
        ['SELECT * FROM events e JOIN persons p ON e.person_id = p.id', 'persons', 'persons'],
        ['SELECT * FROM numbers(10) CROSS JOIN events', 'events', 'events'],
        ['SELECT * FROM numbers(10) CROSS JOIN events', 'numbers', null],
        ['SELECT * FROM `monthly totals`', 'monthly totals', 'monthly totals'],
        ['SELECT * FROM posthog.metrics', 'posthog.metrics', 'posthog.metrics'],
        ['SELECT 1; SELECT * FROM events', 'events', 'events'],
        ["SELECT '🦔' FROM events", 'events', 'events'],
        ['WITH sample AS (SELECT * FROM events) SELECT * FROM sample', 'events', 'events'],
        ['WITH events AS (SELECT * FROM events) SELECT * FROM events', 'events)', 'events'],
        ['WITH first AS (SELECT * FROM events), events AS (SELECT 1) SELECT * FROM first', 'events)', 'events'],
        ['WITH events AS (SELECT 1), second AS (SELECT * FROM events) SELECT * FROM second', 'events)', null],
        [
            'WITH events AS (SELECT * FROM events) SELECT * FROM events UNION ALL SELECT * FROM events',
            'events)',
            'events',
        ],
        [
            'WITH RECURSIVE sample AS (SELECT * FROM events UNION ALL SELECT * FROM sample) SELECT * FROM sample',
            'events',
            'events',
        ],
        [
            'WITH RECURSIVE sample AS (SELECT * FROM events UNION ALL SELECT * FROM sample) SELECT * FROM sample',
            'sample)',
            null,
        ],
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

    it.each([
        ['sample_orders', 'sample.orders'],
        ['sample.orders', 'sample.orders'],
        ['events', 'events'],
        ['missing', undefined],
    ])('resolves catalog metadata for %s', (name, expected) => {
        const tables: Record<string, DatabaseSchemaTable> = {
            'sample.orders': {
                type: 'data_warehouse',
                id: 'sample-orders',
                name: 'sample.orders',
                search_aliases: ['sample_orders', 'events'],
                fields: {},
            },
            events: { type: 'posthog', id: 'events', name: 'events', fields: {} },
        }

        expect(findSqlCatalogTable(tables, name)?.name).toEqual(expected)
    })

    it('shares the cursor-analysis query while preserving document offsets', async () => {
        const query = "SELECT 1;\n  SELECT '🦔' FROM events  \n"
        const analyze = jest.spyOn(parserWorker, 'analyzeTableReference')
        try {
            const reference = await findSqlTableReference(query, query.indexOf('events') + 1)

            expect(analyze).toHaveBeenCalledWith(splitQueries(query)[1].query, 17)
            expect(reference).toEqual({
                name: 'events',
                start: query.indexOf('events'),
                end: query.indexOf('events') + 6,
            })
        } finally {
            analyze.mockRestore()
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
            value: `[Open view definition](http://localhost/project/${getCurrentTeamId()}/sql?open_view=example-view)`,
        })
    })
})
