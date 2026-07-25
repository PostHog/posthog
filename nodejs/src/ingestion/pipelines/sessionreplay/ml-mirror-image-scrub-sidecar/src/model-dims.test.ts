import { modelInputDims } from './dbnet.ts'

describe('modelInputDims', () => {
    // The redaction guarantee is a per-axis ratio between what the model sees and what gets stored,
    // so any per-axis loss between the frame and the model narrows it. Rounding the model input DOWN
    // to the encoder's stride of 32 does exactly that, and worst on short or narrow images: a 63px
    // banner would lose half its height. Collected images are DOM sprites and banners, not just full
    // viewport frames, so these shapes are ordinary rather than exotic.
    it.each([
        ['a short wide banner', 2048, 219],
        ['a single-strip banner', 900, 63],
        ['a narrow tall sidebar', 63, 900],
        ['dimensions one over the stride', 33, 33],
        ['dimensions one under the stride', 31, 31],
        ['an ordinary frame', 894, 503],
    ])('never gives %s less content than it has', (_case, W, H) => {
        const { cw, ch, rw, rh } = modelInputDims(W, H, 736)

        // No content dropped: at ratio 1 the model sees every row and column the frame has.
        expect(cw).toBe(Math.min(W, cw))
        expect(ch).toBe(Math.min(H, ch))
        // The canvas covers the content and lands on the stride, so nothing is cropped to reach it.
        expect(rw).toBeGreaterThanOrEqual(cw)
        expect(rh).toBeGreaterThanOrEqual(ch)
        expect(rw % 32).toBe(0)
        expect(rh % 32).toBe(0)
    })

    it('keeps every row of a frame that fits the budget', () => {
        // 2048x219 is inside 736^2 by area, so it should reach the model whole. Flooring to the
        // stride cut it to 192 rows, which against 73 stored rows is 2.63x, under the 3x the
        // invariant promises.
        const { cw, ch } = modelInputDims(2048, 219, 736)

        expect(cw).toBe(2048)
        expect(ch).toBe(219)
    })
})
