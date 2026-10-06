import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'
import type { InsightApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { fileSystemEntryToAnalytics, insightToAnalytics, newCanvasSpaceIdForPath } from './analyticsUtils'

const canvas = (overrides: Partial<CanvasApi>): CanvasApi =>
    ({
        id: 'c',
        name: 'Canvas',
        kind: 'freeform',
        channel: 'space-1',
        updated_at: '2026-09-01T00:00:00Z',
        ...overrides,
    }) as CanvasApi

const insight = (overrides: Partial<InsightApi>): InsightApi =>
    ({
        short_id: 'abc',
        name: null,
        derived_name: null,
        last_modified_at: '2026-09-01T00:00:00Z',
        created_at: '2026-08-01T00:00:00Z',
        created_by: { id: 1, uuid: 'u1', first_name: 'Ada', last_name: '', email: 'ada@example.com' },
        tags: ['growth', 7],
        ...overrides,
    }) as unknown as InsightApi

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
    test.each([
        ['a space page', '/spaces/space-3', 'space-3'],
        ['a canvas page', '/canvases/board', 'space-1'],
        ['a different open canvas', '/canvases/other', null],
        ['the start page', '/canvases/new', null],
        ['a page with no space', '/analytics', null],
    ])('defaults a new canvas from %s to the right space', (_, path, spaceId) => {
        expect(newCanvasSpaceIdForPath(path, canvas({ id: 'board', channel: 'space-1' }))).toBe(spaceId)
    })

    test.each([
        ['its name', { name: 'Signups' }, 'Signups'],
        ['its derived name when it has no name', { derived_name: 'Pageview count' }, 'Pageview count'],
        ['a fallback when it has neither', {}, 'Untitled insight'],
    ])('names an insight after %s', (_, overrides, name) => {
        expect(insightToAnalytics(insight(overrides)).name).toBe(name)
    })

    it('keeps only string tags and the project-wide access time of an insight', () => {
        const analytics = insightToAnalytics(insight({ last_viewed_at: '2026-09-02T00:00:00Z' }))
        expect(analytics.tags).toEqual(['growth'])
        expect(analytics.lastAccessedAt).toBe('2026-09-02T00:00:00Z')
        expect(analytics.createdBy?.uuid).toBe('u1')
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
            timestampLabel: 'Created',
        })
    })

    test.each([
        ['a non-analytics type', { type: 'feature_flag' }],
        ['a folder', { type: 'folder', ref: undefined }],
    ])('ignores %s in the file system', (_, overrides) => {
        expect(fileSystemEntryToAnalytics(entry(overrides as Partial<FileSystemEntry>))).toBeNull()
    })
})
