import { NodeKind } from '~/queries/schema/schema-general'
import type { DashboardTile, DashboardType } from '~/types'

import { dashboardViewedProperties, sanitizeDashboard } from './dashboardEvents'

describe('dashboardEvents', () => {
    it('keeps metric variable definitions out of a sanitized dashboard', () => {
        const metricVariables = [{ name: 'env', source: 'sql', query: 'SELECT private_value' }]
        const tile = { id: 1, insight: { id: 2, filter_override_context: { dashboard: { metricVariables } } } }
        const dashboard = { id: 7, tiles: [tile], filters: { metricVariables }, persisted_filters: { metricVariables } }

        const sanitized = sanitizeDashboard(dashboard as unknown as DashboardType)

        expect(JSON.stringify(sanitized)).not.toContain('private_value')
    })

    describe('dashboardViewedProperties', () => {
        const dashboard = (tiles: Partial<DashboardTile>[]): DashboardType =>
            ({
                id: 7,
                created_at: '2026-01-01T00:00:00Z',
                is_shared: false,
                pinned: true,
                creation_mode: 'default',
                created_by: { uuid: 'creator' },
                tiles,
            }) as unknown as DashboardType

        const insightTile = (query: unknown, is_sample = false): Partial<DashboardTile> =>
            ({ insight: { query, is_sample } }) as unknown as Partial<DashboardTile>

        const cases: [string, Partial<DashboardTile>[], Record<string, unknown>][] = [
            ['no tiles', [], { item_count: 0, sample_items_count: 0 }],
            [
                'an insight tile with a query',
                [insightTile({ kind: NodeKind.InsightVizNode, source: { kind: NodeKind.TrendsQuery, series: [] } })],
                { item_count: 1, text_count: 1, uses_data_warehouse_source: false, data_warehouse_tiles_count: 0 },
            ],
            ['an insight tile without a query', [insightTile(null)], { item_count: 1, empty_count: 1 }],
            [
                'a sample insight tile that reads the warehouse',
                [insightTile({ kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.DataWarehouseNode }] }, true)],
                {
                    item_count: 1,
                    text_count: 1,
                    sample_items_count: 1,
                    uses_data_warehouse_source: true,
                    data_warehouse_tiles_count: 1,
                },
            ],
            [
                'text and widget tiles',
                [{ text: { body: 'hi' } }, { text: { body: 'there' } }, { widget: {} }] as Partial<DashboardTile>[],
                { item_count: 3, text_tiles_count: 2, widget_tiles_count: 1 },
            ],
            [
                'groups once however many tiles share a key',
                [
                    { group_key: 'a' },
                    { group_key: 'a' },
                    { group_key: 'b' },
                    { group_key: null },
                ] as Partial<DashboardTile>[],
                { item_count: 4, text_tiles_count: 4, group_count: 2 },
            ],
        ]

        it.each(cases)('counts %s', (_, tiles, expected) => {
            expect(dashboardViewedProperties(dashboard(tiles), null, 'viewer')).toEqual({
                created_at: '2026-01-01T00:00:00Z',
                is_shared: false,
                pinned: true,
                creation_mode: 'default',
                viewer_is_creator: false,
                created_by_system: false,
                dashboard_id: 7,
                group_display: 'sections',
                group_count: 0,
                lastRefreshed: undefined,
                refreshAge: undefined,
                sample_items_count: 0,
                uses_data_warehouse_source: false,
                data_warehouse_tiles_count: 0,
                ...expected,
            })
        })

        it('reports the dashboard group display', () => {
            const withTabs = { ...dashboard([]), customization: { group_display: 'tabs' } } as unknown as DashboardType
            expect(dashboardViewedProperties(withTabs, null, 'viewer')).toMatchObject({ group_display: 'tabs' })
        })

        const viewerCases: [string, { uuid: string } | null, string | undefined, boolean | undefined][] = [
            ['the creator views it', { uuid: 'creator' }, 'creator', true],
            ['another user views it', { uuid: 'creator' }, 'viewer', false],
            ['the viewer is unknown', { uuid: 'creator' }, undefined, undefined],
            ['the system created it', null, 'viewer', undefined],
        ]

        it.each(viewerCases)('reports viewer_is_creator when %s', (_, created_by, viewerUuid, expected) => {
            const withCreator = { ...dashboard([]), created_by } as unknown as DashboardType
            expect(dashboardViewedProperties(withCreator, null, viewerUuid)).toMatchObject({
                viewer_is_creator: expected,
                created_by_system: created_by === null,
            })
        })
    })
})
