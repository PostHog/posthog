import { computeBoundaries, computeSegments, computeZones, GridGeometry, TileRect } from './insertTileGeometry'

describe('insertTileGeometry', () => {
    const rect = (top: number, bottom: number, left: number, right: number): TileRect => ({ top, bottom, left, right })

    describe('computeSegments', () => {
        // A clean gap (no tile crosses the line) must draw the line full width — the "line stopped short of
        // empty space" regression. A tile the line passes through must be cut out, padded into the gutter —
        // the "line slices across the card" regression.
        it.each([
            {
                name: 'no tile on the line → full-width segment',
                lineY: 100,
                tiles: [rect(0, 90, 0, 600), rect(110, 200, 0, 600)],
                expected: [{ left: 0, width: 600 }],
            },
            {
                name: 'a straddling tile is cut out (padded by half the margin)',
                lineY: 100,
                tiles: [rect(50, 150, 300, 600)],
                expected: [{ left: 0, width: 292 }],
            },
            {
                name: 'tile straddling the left leaves only the right run',
                lineY: 100,
                tiles: [rect(50, 150, 0, 300)],
                expected: [{ left: 308, width: 292 }],
            },
            {
                name: 'two straddling columns leave the middle gutter',
                lineY: 100,
                tiles: [rect(50, 150, 0, 290), rect(50, 150, 310, 600)],
                expected: [{ left: 298, width: 4 }],
            },
        ])('$name', ({ lineY, tiles, expected }) => {
            expect(computeSegments(lineY, tiles, 600, 16)).toEqual(expected)
        })
    })

    describe('computeZones', () => {
        const unit = 96 // rowHeight 80 + marginY 16
        const colUnit = 50

        it('a tile whose top is on the line yields a drop zone at that row', () => {
            // tile at grid row 5 (top 5*96 = 480), line sits in the gap just above it
            expect(computeZones(472, [rect(480, 700, 0, 300)], unit, colUnit, 16)).toEqual([
                { left: 0, right: 300, targetX: 0, targetY: 5 },
            ])
        })

        it('a tile whose bottom is on the line yields an append-below zone', () => {
            // tile occupies rows 0..4, bottom at 5*96 - 16 = 464; appending lands at row 5
            expect(computeZones(472, [rect(0, 464, 0, 300)], unit, colUnit, 16)).toEqual([
                { left: 0, right: 300, targetX: 0, targetY: 5 },
            ])
        })

        it('targetX comes from the tile column, so right-column tiles insert right', () => {
            expect(computeZones(472, [rect(480, 700, 300, 600)], unit, colUnit, 16)).toEqual([
                { left: 300, right: 600, targetX: 6, targetY: 5 },
            ])
        })

        it('a tile not bordering the line yields no zone (empty column above the line)', () => {
            expect(computeZones(472, [rect(0, 100, 0, 300)], unit, colUnit, 16)).toEqual([])
        })

        it('a stacked tile-above and tile-below at the same boundary dedupe to one zone', () => {
            // above ends at 464 (row 5), below starts at 480 (row 5) — both map to column 0, row 5
            expect(computeZones(472, [rect(0, 464, 0, 300), rect(480, 700, 0, 300)], unit, colUnit, 16)).toEqual([
                { left: 0, right: 300, targetX: 0, targetY: 5 },
            ])
        })
    })

    describe('computeBoundaries', () => {
        const geometry: GridGeometry = { gridWidth: 600, cols: 12, marginX: 16, marginY: 16, rowHeight: 80 }

        it('offers no line above the first row, a line between rows, and an append line below', () => {
            // two stacked full-width tiles: rows 0..4 (top 0, bottom 464) and rows 5..9 (top 480, bottom 944)
            const boundaries = computeBoundaries([rect(0, 464, 0, 600), rect(480, 944, 0, 600)], geometry)

            // one line in the gap (above the second tile) + one append line below the lowest tile — never above row 0
            expect(boundaries.map((b) => b.gridRow)).toEqual([5, 10])
            expect(boundaries[0].lineY).toEqual(472) // 480 - marginY/2
            expect(boundaries[1].lineY).toEqual(952) // 944 + marginY/2
        })

        it('returns nothing for an empty board', () => {
            expect(computeBoundaries([], geometry)).toEqual([])
        })

        it('a tile starting partway down a taller neighbour still gets its own line', () => {
            // left tile spans rows 0..9; right tile starts at row 5 — the line above the right tile must exist,
            // clipped behind the left tile (so it only shows in the right column's gutter onward)
            const boundaries = computeBoundaries([rect(0, 944, 0, 290), rect(480, 944, 310, 600)], geometry)
            const line = boundaries.find((b) => b.gridRow === 5)

            expect(line).not.toBeUndefined()
            // the left tile straddles this line, so the segment starts past it (into the gutter)
            expect(line!.segments[0].left).toBeGreaterThan(290)
            // the drop zone is the right column
            expect(line!.zones).toEqual([{ left: 310, right: 600, targetX: 6, targetY: 5 }])
        })
    })
})
