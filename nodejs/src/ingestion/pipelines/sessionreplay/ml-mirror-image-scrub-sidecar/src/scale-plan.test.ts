import { FLOORS, bindingRatio, requiredRatio } from './floors.ts'
import { type PlanLimits, faceInputScale, fitToCanvas, planScales, scaleToArea } from './scale-plan.ts'

const LIMITS: PlanLimits = {
    framePixels: 450_000,
    textCanvasPixels: 736 * 736,
    storedPixels: 50_000,
    faceInputSide: 640,
    faceTileAbove: 3,
    faceTileAspect: 6,
    stride: 32,
    safetyFactor: 1.3,
}

describe('scale-plan', () => {
    // The four rules the plan exists to keep, asserted over the shape classes that have each broken
    // one of them in production or review. Every case here is a real defect that shipped or nearly did.
    const SHAPES: [string, number, number][] = [
        ['a 1080p desktop frame', 1920, 1080],
        ['a 4K desktop frame', 3840, 2160],
        ['a retina laptop frame', 2880, 1800],
        ['a mobile portrait frame', 390, 844],
        ['a sprite under every budget', 200, 200],
        ['a favicon', 32, 32],
        ['a wide banner', 2048, 219],
        ['a banner past the face tiling threshold', 8000, 60],
        ['a degenerate strip', 100_000, 10],
        ['a degenerate column', 10, 100_000],
    ]

    it.each(SHAPES)('never upscales any stage for %s', (_case, width, height) => {
        const plan = planScales({ width, height }, LIMITS)

        expect(plan.frame.width).toBeLessThanOrEqual(width)
        expect(plan.frame.height).toBeLessThanOrEqual(height)
        expect(plan.text.content.width).toBeLessThanOrEqual(plan.frame.width)
        expect(plan.text.content.height).toBeLessThanOrEqual(plan.frame.height)
        expect(plan.stored.width).toBeLessThanOrEqual(plan.frame.width)
        expect(plan.stored.height).toBeLessThanOrEqual(plan.frame.height)
    })

    it.each(SHAPES)('keeps the frame inside its own budget for %s', (_case, width, height) => {
        // An axis that scales below one pixel floors to one, which leaves the other at full length
        // and the product above the budget by any factor: a 1x50,000,000 source planned ten times it.
        // The per-worker memory model is derived from this budget, so an unbounded frame is an OOM.
        const { frame } = planScales({ width, height }, LIMITS)

        expect(frame.width * frame.height).toBeLessThanOrEqual(LIMITS.framePixels)
    })

    it.each(SHAPES)('bounds the allocated tensor for %s', (_case, width, height) => {
        // Rule 2: a budget on content area does not bound the tensor once a collapsed axis is padded
        // up to the stride. A 100 KB PNG allocated fifteen times the budget this way.
        const { canvas } = planScales({ width, height }, LIMITS).text

        expect(canvas.width * canvas.height).toBeLessThanOrEqual(LIMITS.textCanvasPixels)
        expect(canvas.width % LIMITS.stride).toBe(0)
        expect(canvas.height % LIMITS.stride).toBe(0)
    })

    it.each(SHAPES)('keeps the canvas covering its content for %s', (_case, width, height) => {
        const { content, canvas } = planScales({ width, height }, LIMITS).text

        expect(canvas.width).toBeGreaterThanOrEqual(content.width)
        expect(canvas.height).toBeGreaterThanOrEqual(content.height)
    })

    it.each(SHAPES)('holds the ratio against EVERY detector for %s', (_case, width, height) => {
        // Rule 4, and the finding that motivated the weakest-detector rule: deriving from the text
        // detector alone gave faces 2.15x on an ordinary 1080p frame while the docs promised 3x.
        const plan = planScales({ width, height }, LIMITS)
        const required = bindingRatio()

        const textSeen = Math.min(plan.text.content.width, plan.text.content.height)
        const faceSeen = Math.min(plan.frame.width, plan.frame.height) * plan.face.scale
        const kept = Math.min(plan.stored.width, plan.stored.height)
        // A stored axis floored to one pixel cannot express a ratio; such a frame carries no text.
        if (kept > 1) {
            expect(textSeen / kept).toBeGreaterThanOrEqual(required)
            expect(faceSeen / kept).toBeGreaterThanOrEqual(required)
        }
    })

    it('is the tightest subject that sets the ratio', () => {
        // Whichever subject has least room decides, so adding a detector can only tighten it.
        expect(bindingRatio()).toBe(Math.max(...Object.values(FLOORS).map(requiredRatio)))
        expect(requiredRatio(FLOORS.text)).toBeCloseTo(7 / 3, 5)
    })

    it('respects the stored budget when that is the tighter bound', () => {
        // Two independent bounds: the ratio, and an operator's cap. The smaller wins.
        const tight = planScales({ width: 1920, height: 1080 }, { ...LIMITS, storedPixels: 2_000 })

        expect(tight.stored.width * tight.stored.height).toBeLessThanOrEqual(2_000)
    })

    it('lets a fixed-input detector enlarge a frame smaller than its square', () => {
        // The one allowed upscale: the size belongs to the model, and filling the square is what
        // maximises the subject at it. Only the reduction matters for the ratio, hence the cap at 1.
        expect(faceInputScale({ width: 200, height: 100 }, 640, 3, 6)).toBe(1)
        expect(faceInputScale({ width: 1280, height: 720 }, 640, 3, 6)).toBeCloseTo(0.5, 5)
    })

    it('never returns a zero dimension', () => {
        // A degenerate axis floors to one pixel rather than vanishing: a zero-width buffer is a crash
        // several stages down, far from the shape that caused it.
        const plan = planScales({ width: 100_000, height: 3 }, LIMITS)

        for (const d of [plan.frame, plan.text.content, plan.text.canvas, plan.stored]) {
            expect(d.width).toBeGreaterThanOrEqual(1)
            expect(d.height).toBeGreaterThanOrEqual(1)
        }
    })

    it('scales to an area budget without exceeding it', () => {
        expect(scaleToArea({ width: 2000, height: 1000 }, 500_000)).toBeCloseTo(0.5, 5)
        expect(scaleToArea({ width: 100, height: 100 }, 500_000)).toBe(1)
    })

    it('fits a collapsed axis by shrinking the long one', () => {
        const { canvas } = fitToCanvas({ width: 212_132, height: 2 }, 736 * 736, 32)

        expect(canvas.width * canvas.height).toBeLessThanOrEqual(736 * 736)
        expect(canvas.height).toBe(32)
    })
})
