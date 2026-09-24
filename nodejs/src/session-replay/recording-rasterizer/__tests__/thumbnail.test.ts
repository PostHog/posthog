import { uniformBorderRect } from '../thumbnail'

const BORDER: [number, number, number] = [26, 31, 38]

function frame(
    width: number,
    height: number,
    content: { x: number; y: number; w: number; h: number } | null,
    fill: [number, number, number] = [253, 253, 253]
): Buffer {
    const buffer = Buffer.alloc(width * height * 3)
    for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
            const inside =
                content !== null &&
                x >= content.x &&
                x < content.x + content.w &&
                y >= content.y &&
                y < content.y + content.h
            const [r, g, b] = inside ? fill : BORDER
            const at = (y * width + x) * 3
            buffer[at] = r
            buffer[at + 1] = g
            buffer[at + 2] = b
        }
    }
    return buffer
}

describe('uniformBorderRect', () => {
    it('finds the page in a canvas padded with the player background', () => {
        const buffer = frame(1280, 688, { x: 472, y: 0, w: 336, h: 688 })

        expect(uniformBorderRect(buffer, 1280, 688)).toEqual({ w: 336, h: 688, x: 472, y: 0 })
    })

    it('keeps a frame that is already all content', () => {
        expect(uniformBorderRect(frame(1280, 688, { x: 0, y: 0, w: 1280, h: 688 }), 1280, 688)).toBeNull()
    })

    it('keeps a frame whose border is too thin to bother with', () => {
        expect(uniformBorderRect(frame(1280, 688, { x: 20, y: 0, w: 1240, h: 688 }), 1280, 688)).toBeNull()
    })

    it('keeps a dark page rather than cropping into it', () => {
        // The case a luma threshold gets wrong: dark content, not a border.
        const buffer = frame(1280, 688, { x: 0, y: 0, w: 1280, h: 688 }, [30, 34, 41])

        expect(uniformBorderRect(buffer, 1280, 688)).toBeNull()
    })

    it('keeps a blank frame whole', () => {
        expect(uniformBorderRect(frame(1280, 688, null), 1280, 688)).toBeNull()
    })

    it('ignores a truncated buffer', () => {
        expect(uniformBorderRect(Buffer.alloc(100), 1280, 688)).toBeNull()
    })

    it('crops vertical padding too', () => {
        expect(uniformBorderRect(frame(800, 600, { x: 100, y: 80, w: 600, h: 300 }), 800, 600)).toEqual({
            w: 600,
            h: 300,
            x: 100,
            y: 80,
        })
    })
})
