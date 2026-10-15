import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import { newCanvasSpaceIdForPath } from './viewsUtils'

const canvas = (overrides: Partial<CanvasApi>): CanvasApi =>
    ({
        id: 'c',
        name: 'Canvas',
        kind: 'freeform',
        channel: 'space-1',
        updated_at: '2026-09-01T00:00:00Z',
        ...overrides,
    }) as CanvasApi

describe('viewsUtils', () => {
    test.each([
        ['a space page', '/spaces/space-3', 'space-3'],
        ['a canvas page', '/canvases/board', 'space-1'],
        ['a different open canvas', '/canvases/other', null],
        ['the start page', '/canvases/new', null],
        ['a page with no space', '/views', null],
    ])('defaults a new canvas from %s to the right space', (_, path, spaceId) => {
        expect(newCanvasSpaceIdForPath(path, canvas({ id: 'board', channel: 'space-1' }))).toBe(spaceId)
    })
})
