import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import { fileSystemEntryToAnalytics, newCanvasSpaceIdForPath } from './analyticsUtils'

const canvas = (overrides: Partial<CanvasApi>): CanvasApi =>
    ({
        id: 'c',
        name: 'Canvas',
        kind: 'freeform',
        channel: 'space-1',
        updated_at: '2026-09-01T00:00:00Z',
        ...overrides,
    }) as CanvasApi

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

    test.each([
        ['a space page', '/spaces/space-3', 'space-3'],
        ['a canvas page', '/canvases/board', 'space-1'],
        ['a different open canvas', '/canvases/other', null],
        ['the start page', '/canvases/new', null],
        ['a page with no space', '/analytics', null],
    ])('defaults a new canvas from %s to the right space', (_, path, spaceId) => {
        expect(newCanvasSpaceIdForPath(path, canvas({ id: 'board', channel: 'space-1' }))).toBe(spaceId)
    })
})
