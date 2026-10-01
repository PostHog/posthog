import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'
import type { DashboardBasicApi } from 'products/dashboards/frontend/generated/api.schemas'
import type { NotebookMinimalApi } from 'products/notebooks/frontend/generated/api.schemas'

import { ViewItem, filterViews, mergeViews, newCanvasSpaceIdForPath } from './viewsUtils'

const canvas = (overrides: Partial<CanvasApi>): CanvasApi =>
    ({
        id: 'c',
        name: 'Canvas',
        kind: 'freeform',
        channel: 'space-1',
        updated_at: '2026-09-01T00:00:00Z',
        ...overrides,
    }) as CanvasApi

const notebook = (overrides: Partial<NotebookMinimalApi>): NotebookMinimalApi =>
    ({
        short_id: 'n',
        title: 'Notebook',
        deleted: false,
        last_modified_at: '2026-09-01T00:00:00Z',
        ...overrides,
    }) as NotebookMinimalApi

const dashboard = (overrides: Partial<DashboardBasicApi>): DashboardBasicApi =>
    ({
        id: 1,
        name: 'Dashboard',
        deleted: false,
        last_viewed_at: null,
        created_at: '2026-09-01T00:00:00Z',
        ...overrides,
    }) as DashboardBasicApi

const summary = (items: ViewItem[]): string[] => items.map((item) => `${item.type}:${item.id}`)

describe('viewsUtils', () => {
    it('merges every type into one list, most recent first, and leaves out component canvases and deleted views', () => {
        const items = mergeViews({
            canvases: [
                canvas({ id: 'grid', kind: 'grid', updated_at: '2026-09-20T00:00:00Z' }),
                canvas({ id: 'widget', kind: 'component', updated_at: '2026-09-29T00:00:00Z' }),
                canvas({ id: 'board', kind: 'freeform', updated_at: '2026-09-05T00:00:00Z' }),
            ],
            notebooks: [
                notebook({ short_id: 'notes', last_modified_at: '2026-09-25T00:00:00Z' }),
                notebook({ short_id: 'gone', deleted: true, last_modified_at: '2026-09-28T00:00:00Z' }),
            ],
            dashboards: [
                dashboard({ id: 7, last_viewed_at: '2026-09-10T00:00:00Z', created_at: '2026-08-01T00:00:00Z' }),
                dashboard({ id: 8, last_viewed_at: null, created_at: '2026-09-15T00:00:00Z' }),
            ],
            spaceNames: {},
        })

        expect(summary(items)).toEqual(['notebook:notes', 'canvas:grid', 'dashboard:8', 'dashboard:7', 'canvas:board'])
        expect(filterViews(items, 'dashboard').map((item) => item.timestampLabel)).toEqual(['Created', 'Viewed'])
    })

    it('names the space a canvas belongs to, and leaves it out when the space is unknown', () => {
        const items = mergeViews({
            canvases: [
                canvas({ id: 'known', channel: 'space-1', updated_at: '2026-09-02T00:00:00Z' }),
                canvas({ id: 'unknown', channel: 'space-2' }),
            ],
            notebooks: [],
            dashboards: [],
            spaceNames: { 'space-1': 'growth' },
        })

        expect(items.map((item) => item.spaceName)).toEqual(['growth', null])
    })

    test.each([
        ['a space page', '/spaces/space-3', 'space-3'],
        ['a canvas page', '/canvases/board', 'space-1'],
        ['a canvas that is not listed', '/canvases/other', null],
        ['the start page', '/canvases/new', null],
        ['a page with no space', '/views', null],
    ])('defaults a new canvas from %s to the right space', (_, path, spaceId) => {
        const items = mergeViews({
            canvases: [canvas({ id: 'board', channel: 'space-1' })],
            notebooks: [notebook({ short_id: 'board' })],
            dashboards: [],
            spaceNames: {},
        })

        expect(newCanvasSpaceIdForPath(path, items)).toBe(spaceId)
    })
})
