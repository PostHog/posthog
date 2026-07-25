import { modelInputDims } from './dbnet.ts'
import { assertResolutionInvariant, storedDimsFor } from './src-image.ts'
import { yunetFrameScale } from './yunet.ts'

describe('assertResolutionInvariant', () => {
    // The guarantee is that anything still legible in the stored image was large enough at the model
    // for the detector to have found it. It lives between the MODEL INPUT and the stored size, so it
    // can be broken three ways: storing too much, detecting too little, or shrinking the frame again
    // after the budgets were set. The third is the one no reviewer would catch by reading the two
    // pixel numbers, which is why DET_FACTOR is an argument rather than an assumption.
    it.each([
        ['the derived defaults', 450_000, 50_000, 1],
        ['a larger pair at the same ratio', 900_000, 100_000, 1],
        ['detection well above the floor', 2_560_000, 50_000, 1],
    ])('accepts %s', (_case, detect, store, detFactor) => {
        expect(() => assertResolutionInvariant(detect, store, detFactor)).not.toThrow()
    })

    it.each([
        ['storing everything that was detected', 2_560_000, 2_560_000, 1],
        ['a ratio just under the floor', 1_000_000, 125_000, 1],
        ['budgets that pass but a DET_FACTOR that spends the margin', 450_000, 50_000, 0.75],
        // 2.996x: rounding the ratio to two places before comparing printed "3.00" and let it pass.
        ['a ratio that only rounds up to the floor', 449_000, 50_000, 1],
    ])('rejects %s', (_case, detect, store, detFactor) => {
        expect(() => assertResolutionInvariant(detect, store, detFactor)).toThrow(/invariant violated/)
    })
})

describe('storedDimsFor', () => {
    // The caps only bind images above them, so checking the caps says nothing about an image under
    // both: it would be stored at the size the model saw it, with no margin at all. Text at 4px
    // would be as readable in the artifact as it was invisible to a detector needing 9px. Small
    // collected sprites are exactly that shape, so this has to hold per image, not per config.
    it.each([
        ['a sprite under both caps', 200, 200],
        ['a 1080p frame after the decode cap', 894, 503],
        ['a short wide banner', 2048, 219],
        ['a narrow tall sidebar', 63, 900],
        ['a frame whose axes floor differently', 1001, 337],
    ])('keeps %s at least 3x smaller than what the model saw, on both axes', (_case, W, H) => {
        const model = modelInputDims(W, H, 736)

        const stored = storedDimsFor(W, H, model.cw, model.ch)

        expect(model.cw / stored.width).toBeGreaterThanOrEqual(3)
        expect(model.ch / stored.height).toBeGreaterThanOrEqual(3)
    })

    it.each([
        ['a 1080p frame after the decode cap', 894, 503],
        ['a square frame at the cap', 671, 671],
        ['a tall mobile frame', 456, 988],
    ])('holds for the FACE detector too on %s', (_case, W, H) => {
        // YuNet letterboxes into a fixed square, so on anything longer than that it sees less of the
        // frame than DBNet does and its margin is the smaller one. Deriving the stored size from the
        // text detector alone published a guarantee that held for one of the three detectors: a
        // 1080p frame gave faces 2.15x while the docstring promised 3x.
        const model = modelInputDims(W, H, 736)
        const faceScale = yunetFrameScale(W, H)

        const stored = storedDimsFor(W, H, model.cw, model.ch, undefined, faceScale)

        expect((W * faceScale) / stored.width).toBeGreaterThanOrEqual(3)
        expect((H * faceScale) / stored.height).toBeGreaterThanOrEqual(3)
    })

    it('never stores more than the source has', () => {
        const model = modelInputDims(64, 64, 736)

        const stored = storedDimsFor(64, 64, model.cw, model.ch)

        expect(stored.width).toBeLessThanOrEqual(64)
        expect(stored.height).toBeLessThanOrEqual(64)
    })
})
