import { UndecodableImageError } from './image-input.ts'
import { type SvgRasterizer, isSvgDocument, startSvgRasterizer } from './svg.ts'

// cwd-relative rather than import.meta, which jest's CJS transform cannot load (see qr.ts).
const CHILD = `${process.cwd()}/src/svg-rasterizer-process.mjs`
const SQUARE = Buffer.from(
    "<svg xmlns='http://www.w3.org/2000/svg' width='16' height='8'><rect width='16' height='8' fill='red'/></svg>"
)
const SLOW = Buffer.from(
    `<svg xmlns='http://www.w3.org/2000/svg' width='8' height='8'>${"<circle r='1e6' stroke='red' stroke-width='1e7' fill='none'/>".repeat(40)}</svg>`
)

describe('svg', () => {
    let rasterizer: SvgRasterizer | undefined

    afterEach(async () => {
        await rasterizer?.close()
        rasterizer = undefined
    })

    it.each([
        ['an svg document', SQUARE, true],
        [
            'one after a BOM and whitespace',
            Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from(' \n'), SQUARE]),
            true,
        ],
        ['a png', Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), false],
        ['a jpeg', Buffer.from([0xff, 0xd8, 0xff]), false],
        ['an empty body', Buffer.alloc(0), false],
    ])('tells %s by its first bytes', (_label, input, expected) => {
        expect(isSvgDocument(input)).toBe(expected)
    })

    it('renders an svg to png and refuses one it cannot render', async () => {
        rasterizer = await startSvgRasterizer(1, CHILD, 5_000, 10_000)
        const png = await rasterizer.rasterize(SQUARE)
        expect(png.subarray(0, 4).toString('latin1')).toBe('\x89PNG')
        await expect(rasterizer.rasterize(Buffer.from('<svg'))).rejects.toMatchObject({ reason: 'svg_refused' })
    })

    it('kills a render that runs past its deadline and serves the next one', async () => {
        rasterizer = await startSvgRasterizer(1, CHILD, 200, 30_000)
        const slow = rasterizer.rasterize(SLOW)
        const next = rasterizer.rasterize(SQUARE)
        await expect(slow).rejects.toBeInstanceOf(UndecodableImageError)
        await expect(slow).rejects.toMatchObject({ reason: 'svg_timeout' })
        expect((await next).subarray(0, 4).toString('latin1')).toBe('\x89PNG')
    })
})
