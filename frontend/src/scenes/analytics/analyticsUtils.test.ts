import { FileSystemEntry } from '~/queries/schema/schema-general'

import { fileSystemEntryToAnalytics, fromPostHogProducts } from './analyticsUtils'

const entry = (overrides: Partial<FileSystemEntry>): FileSystemEntry =>
    ({
        id: 'fs-1',
        path: 'Unfiled/Dashboards/Revenue a\\/b',
        type: 'dashboard',
        ref: '12',
        created_at: '2026-08-01T00:00:00Z',
        meta: { created_by: 1 },
        ...overrides,
    }) as FileSystemEntry

describe('analyticsUtils', () => {
    it('lists the ready-made views By PostHog, leaving out Product analytics, which is the Insights row', () => {
        expect(fromPostHogProducts().map(({ key }) => key)).toEqual([
            'web_analytics',
            'marketing_analytics',
            'mcp_analytics',
            'session_replay',
            'replay_vision',
            'activity',
            'heatmap',
        ])
    })

    it('reads an item from its file system row, resolving the creator and the escaped name', () => {
        const users = [{ id: 1, uuid: 'u1', first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com' }]
        const analytics = fileSystemEntryToAnalytics(entry({}), users)
        expect(analytics).toMatchObject({
            type: 'dashboard',
            id: '12',
            name: 'Revenue a/b',
            href: '/dashboard/12',
            createdBy: { uuid: 'u1', first_name: 'Ada' },
        })
    })

    test.each([
        ['a non-analytics type', { type: 'feature_flag' }],
        ['a folder', { type: 'folder', ref: undefined }],
    ])('ignores %s in the file system', (_, overrides) => {
        expect(fileSystemEntryToAnalytics(entry(overrides as Partial<FileSystemEntry>))).toBeNull()
    })
})
