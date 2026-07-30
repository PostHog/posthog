import { isUniform } from './scrub.ts'

function frame(width: number, height: number, fill: [number, number, number]): Parameters<typeof isUniform>[0] {
    const data = Buffer.alloc(width * height * 3)
    for (let i = 0; i < data.length; i += 3) {
        data[i] = fill[0]
        data[i + 1] = fill[1]
        data[i + 2] = fill[2]
    }
    return { data, W: width, H: height, format: 'png', inputPixels: width * height }
}

describe('isUniform', () => {
    // Frames it reports as uniform skip detection entirely, so anything it wrongly accepts is text
    // that never reaches DBNet. A tolerance, or the same check over a thumbnail, would accept a
    // single line of 14px text in a 1080p frame once it averages into the background.
    it.each([
        ['one differing pixel in the middle', 1920 * 540 * 3 + 960 * 3],
        ['one differing pixel in the last row', 1920 * 1079 * 3],
        ['one differing pixel adjacent to the first', 3],
    ])('rejects a frame with %s', (_case, offset) => {
        const f = frame(1920, 1080, [255, 255, 255])
        f.data[offset + 1] = 254

        expect(isUniform(f)).toBe(false)
    })

    it('accepts a frame that is one exact colour', () => {
        expect(isUniform(frame(1920, 1080, [243, 244, 246]))).toBe(true)
    })
})
