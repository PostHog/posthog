import {
    AmbientBlend,
    type AmbientGrid,
    averageColor,
    edgeAligned,
    extendGrid,
    gridSize,
    isBoxed,
    parseCssColor,
    type Rgba,
} from 'scenes/session-recordings/player/playerFrameAmbientSampling'

describe('playerFrameAmbientSampling', () => {
    test.each([
        ['rgb(12, 34, 56)', [12, 34, 56, 1]],
        ['rgba(12, 34, 56, 0.25)', [12, 34, 56, 0.25]],
        ['rgb(12 34 56 / 0.5)', [12, 34, 56, 0.5]],
        ['rgb(12 34 56 / 40%)', [12, 34, 56, 0.4]],
        ['rgba(0, 0, 0, 0)', [0, 0, 0, 0]],
        ['transparent', null],
        ['color(srgb 1 0 0)', null],
    ])('parses computed color %s', (value, expected) => {
        expect(parseCssColor(value)).toEqual(expected)
    })

    test.each([
        ['portrait phone in a wide player', { width: 1200, height: 700 }, { width: 320, height: 700 }, true],
        ['wide desktop in a tall player', { width: 600, height: 900 }, { width: 600, height: 340 }, true],
        ['recording that fills the player', { width: 1200, height: 700 }, { width: 1190, height: 700 }, false],
    ])('decides a %s is boxed', (_, container, recording, expected) => {
        expect(isBoxed(container, recording)).toEqual(expected)
    })

    test.each([
        ['portrait phone', { width: 390, height: 844 }, { columns: 8, rows: 16 }],
        ['wide desktop', { width: 1920, height: 1080 }, { columns: 8, rows: 5 }],
        ['tall narrow strip', { width: 100, height: 2000 }, { columns: 8, rows: 16 }],
    ])('sizes the grid to a %s', (_, recording, expected) => {
        expect(gridSize(recording)).toEqual(expected)
    })

    test.each([
        ['ignores unreadable stops', [[0, 0, 0, 255], null, [100, 50, 20, 255]], [50, 25, 10, 255]],
        ['has nothing to average', [null, null], null],
    ])('averages colors when it %s', (_, colors, expected) => {
        expect(averageColor(colors as (Rgba | null)[])).toEqual(expected)
    })

    test.each([
        ['first cell', 0, 3],
        ['last cell', 7, 429],
    ])('puts the %s on the recording edge', (_, index, expected) => {
        expect(edgeAligned(index, 8, 432)).toEqual(expected)
    })

    it('extends each recording edge outward into the bars', () => {
        const left = [10, 20, 30, 255]
        const right = [40, 50, 60, 255]
        const grid = { columns: 2, rows: 1, pixels: new Uint8ClampedArray([...left, ...right]) }

        const extended = extendGrid(
            grid,
            { left: 100, top: 0, width: 20, height: 10 },
            { left: 0, top: 0, width: 220, height: 10 }
        )

        const cells = Array.from({ length: extended.grid.columns }, (_, column) =>
            Array.from(extended.grid.pixels.subarray(column * 4, column * 4 + 4))
        )
        expect(cells.slice(0, 11)).toEqual(Array(11).fill(left))
        expect(cells.slice(11)).toEqual(Array(cells.length - 11).fill(right))
        expect(extended.area).toEqual({ left: 0, top: 0, width: cells.length * 10, height: 10 })
    })

    it('shows the first colors at once, then eases toward new ones without jumping', () => {
        const grid = (value: number): AmbientGrid => ({
            columns: 1,
            rows: 1,
            pixels: new Uint8ClampedArray([value, value, value, 255]),
        })
        const blend = new AmbientBlend()

        expect(blend.setTarget(grid(200))).toBe(true)
        expect(Array.from(blend.pixels)).toEqual([200, 200, 200, 255])

        expect(blend.setTarget(grid(0))).toBe(false)
        blend.step(1000)
        expect(blend.step(1100)).toEqual({ changed: true, settled: false })
        const afterShortStep = blend.pixels[0]
        expect(afterShortStep).toBeGreaterThan(150)
        expect(afterShortStep).toBeLessThan(200)

        expect(blend.step(61_100)).toEqual({ changed: true, settled: true })
        expect(Array.from(blend.pixels)).toEqual([0, 0, 0, 255])
    })
})
