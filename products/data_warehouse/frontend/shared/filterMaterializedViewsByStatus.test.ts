import type { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { filterMaterializedViewsByStatus, MaterializationStatusFilter } from './filterMaterializedViewsByStatus'

describe('filterMaterializedViewsByStatus', () => {
    it.each<{ statuses: MaterializationStatusFilter[]; expected: string[] }>([
        { statuses: [], expected: ['failed', 'running', 'completed', 'plain'] },
        { statuses: ['Running'], expected: ['running'] },
        { statuses: ['Completed'], expected: ['completed'] },
        { statuses: ['Failed', 'Running'], expected: ['failed', 'running'] },
    ])('matches any selected status: $statuses', ({ statuses, expected }) => {
        const items: TreeDataItem[] = [
            ['failed', 'Failed', true],
            ['running', 'Running', true],
            ['completed', 'Completed', true],
            ['plain', 'Running', false],
        ].map(([id, status, isMaterialized]) => ({
            id: String(id),
            name: String(id),
            record: { type: 'view', view: { is_materialized: isMaterialized, status } },
        }))

        expect(filterMaterializedViewsByStatus(items, statuses).map((item) => item.id)).toEqual(expected)
    })

    it('keeps failed materialized views and their columns inside matching folders', () => {
        const columns: TreeDataItem[] = [{ id: 'column', name: 'total', record: { type: 'column' } }]
        const views: TreeDataItem[] = [
            {
                id: 'failed',
                name: 'failed',
                record: { type: 'view', view: { is_materialized: true, status: 'Failed' } },
                children: columns,
            },
            {
                id: 'healthy',
                name: 'healthy',
                record: { type: 'view', view: { is_materialized: true, status: 'Completed' } },
            },
            {
                id: 'running',
                name: 'running',
                record: { type: 'view', view: { is_materialized: true, status: 'Running' } },
            },
            {
                id: 'plain',
                name: 'plain',
                record: { type: 'view', view: { is_materialized: false, status: 'Failed' } },
            },
            { id: 'pending', name: 'pending', record: { type: 'view', view: { is_materialized: true, status: null } } },
        ]
        const folder: TreeDataItem = {
            id: 'folder',
            name: 'Reporting',
            record: { type: 'folder', folderType: 'view-folder' },
            children: views,
        }
        const paused: TreeDataItem = {
            id: 'paused',
            name: 'paused',
            record: {
                type: 'view',
                view: {
                    is_materialized: true,
                    status: 'Failed',
                    suspended: { clickhouse: { reason: 'Example failure' } },
                },
            },
        }
        const root: TreeDataItem = {
            id: 'views',
            name: 'Views',
            record: { type: 'views' },
            children: [folder, paused, { ...folder, id: 'empty', children: [views[1]] }],
        }
        const result = filterMaterializedViewsByStatus(
            [
                { id: 'sources', name: 'Sources', record: { type: 'sources' }, children: views },
                root,
                { id: 'drafts', name: 'Drafts', record: { type: 'drafts' } },
            ],
            ['Failed']
        )

        expect(result).toEqual([{ ...root, children: [{ ...folder, children: [views[0]] }, paused] }])
        expect(result[0].children![0].children![0].children).toBe(columns)
        expect(folder.children).toHaveLength(5)
    })

    it.each([
        ['empty', [], []],
        ['loading', [{ id: 'loading', name: 'Loading...', type: 'loading-indicator' }], ['views']],
    ])('distinguishes %s views from a completed filter with no matches', (_name, children, expectedIds) => {
        const result = filterMaterializedViewsByStatus(
            [{ id: 'views', name: 'Views', record: { type: 'views' }, children: children as TreeDataItem[] }],
            ['Failed']
        )
        expect(result.map((item) => item.id)).toEqual(expectedIds)
    })
})
