import { changedTileLayouts, layoutsForTiles } from './crossProjectLayouts'
import type { CrossProjectDashboardTileApi } from './generated/api.schemas'

const tile = (id: string, layouts?: Record<string, unknown>): CrossProjectDashboardTileApi =>
    ({ id, project_id: 1, insight_id: 2, layouts }) as CrossProjectDashboardTileApi

describe('crossProjectLayouts', () => {
    describe('layoutsForTiles', () => {
        it('flows unpositioned tiles two per row instead of stacking them at the origin', () => {
            const result = layoutsForTiles([tile('a'), tile('b'), tile('c')])

            expect(result.sm.map(({ i, x, y, w }) => ({ i, x, y, w }))).toEqual([
                { i: 'a', x: 0, y: 0, w: 6 },
                { i: 'b', x: 6, y: 0, w: 6 },
                { i: 'c', x: 0, y: 5, w: 6 },
            ])
        })

        it('uses one column at the narrow breakpoint', () => {
            const result = layoutsForTiles([tile('a'), tile('b')])

            expect(result.xs.map(({ i, x, y, w }) => ({ i, x, y, w }))).toEqual([
                { i: 'a', x: 0, y: 0, w: 1 },
                { i: 'b', x: 0, y: 5, w: 1 },
            ])
        })

        it('prefers a stored layout over the default', () => {
            const result = layoutsForTiles([tile('a', { sm: { x: 3, y: 7, w: 4, h: 2 } })])

            expect(result.sm[0]).toEqual({ i: 'a', x: 3, y: 7, w: 4, h: 2 })
        })
    })

    describe('changedTileLayouts', () => {
        it('writes nothing when the grid reports the arrangement already stored', () => {
            const tiles = [tile('a', { sm: { x: 0, y: 0, w: 6, h: 5 }, xs: { x: 0, y: 0, w: 1, h: 5 } })]

            const updates = changedTileLayouts(tiles, {
                sm: [{ i: 'a', x: 0, y: 0, w: 6, h: 5 }],
                xs: [{ i: 'a', x: 0, y: 0, w: 1, h: 5 }],
            })

            expect(updates).toEqual([])
        })

        it('writes only the tile that moved', () => {
            const tiles = [tile('a', { sm: { x: 0, y: 0, w: 6, h: 5 } }), tile('b', { sm: { x: 6, y: 0, w: 6, h: 5 } })]

            const updates = changedTileLayouts(tiles, {
                sm: [
                    { i: 'a', x: 0, y: 0, w: 6, h: 5 },
                    { i: 'b', x: 6, y: 5, w: 6, h: 5 },
                ],
            })

            expect(updates.map((update) => update.tileId)).toEqual(['b'])
            expect(updates[0].layouts.sm).toEqual({ x: 6, y: 5, w: 6, h: 5 })
        })

        it('treats a first arrangement of an unpositioned tile as a change', () => {
            const updates = changedTileLayouts([tile('a')], { sm: [{ i: 'a', x: 2, y: 1, w: 4, h: 3 }] })

            expect(updates).toHaveLength(1)
            expect(updates[0].layouts.sm).toEqual({ x: 2, y: 1, w: 4, h: 3 })
        })

        it('keeps a stored size the grid did not report', () => {
            const tiles = [tile('a', { sm: { x: 0, y: 0, w: 6, h: 5 }, xs: { x: 0, y: 3, w: 1, h: 5 } })]

            const updates = changedTileLayouts(tiles, { sm: [{ i: 'a', x: 1, y: 0, w: 6, h: 5 }] })

            expect(updates[0].layouts.xs).toEqual({ x: 0, y: 3, w: 1, h: 5 })
        })
    })
})
