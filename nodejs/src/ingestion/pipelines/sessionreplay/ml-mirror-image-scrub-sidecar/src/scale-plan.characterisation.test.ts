import { modelInputDims } from './dbnet.ts'
import { adaptiveDetLimit } from './scrub.ts'
import { SCRUB_MAX_PIXELS, storedDimsFor } from './src-image.ts'
import { yunetFrameScale } from './yunet.ts'

/**
 * What the geometry does today, pinned before it is rewritten.
 *
 * Not an assertion that these numbers are right: several are the subject of open findings. They are
 * here so a rewrite has to be deliberate about every shape it changes, rather than discovering the
 * change in production. Delete a row only alongside the reason it moved.
 */
describe('scale geometry, as it currently behaves', () => {
    /** The whole chain for one source, as a reader would have to reconstruct it from five files. */
    function plan(sourceW: number, sourceH: number) {
        const decodeScale = Math.min(1, Math.sqrt(SCRUB_MAX_PIXELS / (sourceW * sourceH)))
        const frameW = Math.max(1, Math.round(sourceW * decodeScale))
        const frameH = Math.max(1, Math.round(sourceH * decodeScale))
        const model = modelInputDims(frameW, frameH, adaptiveDetLimit(frameW, frameH))
        const stored = storedDimsFor(frameW, frameH, model.cw, model.ch, undefined, yunetFrameScale(frameW, frameH))
        return {
            frame: `${frameW}x${frameH}`,
            textContent: `${model.cw}x${model.ch}`,
            textCanvas: `${model.rw}x${model.rh}`,
            stored: `${stored.width}x${stored.height}`,
        }
    }

    it.each([
        ['a 1080p desktop frame', 1920, 1080],
        ['a 4K desktop frame', 3840, 2160],
        ['a retina laptop frame', 2880, 1800],
        ['a mobile portrait frame', 390, 844],
        ['a small sprite under every cap', 200, 200],
        ['a tiny favicon', 32, 32],
        ['a wide banner', 2048, 219],
        ['a banner past the tiling threshold', 8000, 60],
        ['a degenerate strip', 100000, 10],
        ['a degenerate column', 10, 100000],
        ['a square at the cap', 671, 671],
    ])('%s', (_case, W, H) => {
        expect(plan(W, H)).toMatchSnapshot()
    })
})
