import type { ChartDimensions } from '../../../core/types'
import {
    computePieLayout,
    computeSliceAngles,
    DEFAULT_START_ANGLE,
    hitTestSlice,
    type ResolvedPieSlice,
    sliceHoverOffset,
    sliceLabelPosition,
} from './pie-layout'

const DIMENSIONS: ChartDimensions = {
    width: 400,
    height: 400,
    plotLeft: 0,
    plotTop: 0,
    plotWidth: 400,
    plotHeight: 400,
}

const SLICES: ResolvedPieSlice[] = [
    { key: 'a', label: 'A', value: 1, color: '#111' },
    { key: 'b', label: 'B', value: 2, color: '#222' },
    { key: 'c', label: 'C', value: 1, color: '#333' },
]

describe('computePieLayout', () => {
    it('centres the pie within the plot area and reserves room for hover offset', () => {
        const layout = computePieLayout(DIMENSIONS, { hoverOffset: 16 })
        expect(layout.cx).toBe(200)
        expect(layout.cy).toBe(200)
        // (min(plotWidth, plotHeight) / 2) - hoverOffset = 200 - 16 = 184
        expect(layout.outerRadius).toBe(184)
        expect(layout.innerRadius).toBe(0)
    })

    it('honours innerRadius as a fraction of the outer radius', () => {
        const layout = computePieLayout(DIMENSIONS, { innerRadius: 0.5, hoverOffset: 0 })
        expect(layout.outerRadius).toBe(200)
        expect(layout.innerRadius).toBe(100)
    })

    it('clamps innerRadius into [0, 1]', () => {
        const big = computePieLayout(DIMENSIONS, { innerRadius: 5, hoverOffset: 0 })
        expect(big.innerRadius).toBe(big.outerRadius)
        const negative = computePieLayout(DIMENSIONS, { innerRadius: -1, hoverOffset: 0 })
        expect(negative.innerRadius).toBe(0)
    })

    it('returns a zero radius rather than going negative when the plot is tiny', () => {
        const tiny: ChartDimensions = { ...DIMENSIONS, plotWidth: 10, plotHeight: 10 }
        const layout = computePieLayout(tiny, { hoverOffset: 16 })
        expect(layout.outerRadius).toBe(0)
    })
})

describe('computeSliceAngles', () => {
    it('returns one entry per slice with cumulative angles', () => {
        const angles = computeSliceAngles(SLICES, 4, 0)
        expect(angles).toHaveLength(3)
        expect(angles[0].startAngle).toBeCloseTo(0)
        expect(angles[0].endAngle).toBeCloseTo(Math.PI / 2) // 1/4 of full circle
        expect(angles[1].endAngle).toBeCloseTo((3 / 4) * Math.PI * 2)
        expect(angles[2].endAngle).toBeCloseTo(Math.PI * 2)
    })

    it('records the slice index so callers can map back to the original slice array', () => {
        const angles = computeSliceAngles(SLICES, 4)
        expect(angles.map((a) => a.sliceIndex)).toEqual([0, 1, 2])
    })

    it('exposes each slice as a fraction of the total', () => {
        const angles = computeSliceAngles(SLICES, 4)
        expect(angles[0].fraction).toBeCloseTo(0.25)
        expect(angles[1].fraction).toBeCloseTo(0.5)
        expect(angles[2].fraction).toBeCloseTo(0.25)
    })

    it('returns an empty array when total is zero or slices are empty', () => {
        expect(computeSliceAngles(SLICES, 0)).toEqual([])
        expect(computeSliceAngles([], 10)).toEqual([])
    })

    it('honours a custom start angle', () => {
        const angles = computeSliceAngles(SLICES, 4, DEFAULT_START_ANGLE)
        expect(angles[0].startAngle).toBeCloseTo(-Math.PI / 2)
    })
})

describe('hitTestSlice', () => {
    const layout = computePieLayout(DIMENSIONS, { hoverOffset: 0 })
    const angles = computeSliceAngles(SLICES, 4, 0)

    it('returns the slice index containing the cursor', () => {
        // Cursor inside slice 0 (0 → π/2 radians; midpoint at π/4 ≈ +x,+y direction).
        const x = layout.cx + Math.cos(Math.PI / 4) * 50
        const y = layout.cy + Math.sin(Math.PI / 4) * 50
        expect(hitTestSlice(x, y, layout, angles)).toBe(0)
    })

    it('returns -1 when the cursor is outside the outer radius', () => {
        expect(hitTestSlice(layout.cx + 1000, layout.cy, layout, angles)).toBe(-1)
    })

    it('returns -1 when the cursor is inside the donut hole', () => {
        const donutLayout = computePieLayout(DIMENSIONS, { innerRadius: 0.5, hoverOffset: 0 })
        expect(hitTestSlice(donutLayout.cx, donutLayout.cy, donutLayout, angles)).toBe(-1)
    })

    it('returns -1 for an empty slice array', () => {
        expect(hitTestSlice(layout.cx, layout.cy + 50, layout, [])).toBe(-1)
    })

    it('finds the correct slice for cursors at large angles (wrap around)', () => {
        // Use a start angle of -π/2 (12 o'clock). Cursor at +x direction (3 o'clock)
        // sits a quarter of the way round — inside slice 1.
        const wrapAngles = computeSliceAngles(SLICES, 4, -Math.PI / 2)
        const x = layout.cx + 50
        const y = layout.cy
        expect(hitTestSlice(x, y, layout, wrapAngles)).toBe(1)
    })
})

describe('sliceLabelPosition', () => {
    it('places the label along the bisector between inner and outer radii', () => {
        const layout = computePieLayout(DIMENSIONS, { hoverOffset: 0 })
        const angles = computeSliceAngles(SLICES, 4, 0)
        const pos = sliceLabelPosition(layout, angles[0])
        // Midpoint angle of slice 0 (0 → π/2) is π/4. labelR = outerRadius / 2.
        const expectedR = layout.outerRadius / 2
        expect(pos.x).toBeCloseTo(layout.cx + Math.cos(Math.PI / 4) * expectedR)
        expect(pos.y).toBeCloseTo(layout.cy + Math.sin(Math.PI / 4) * expectedR)
    })
})

describe('sliceHoverOffset', () => {
    it('returns (0, 0) when not hovered', () => {
        const angles = computeSliceAngles(SLICES, 4, 0)
        expect(sliceHoverOffset(angles[0], false, 16)).toEqual({ dx: 0, dy: 0 })
    })

    it('returns (0, 0) when hover offset is disabled', () => {
        const angles = computeSliceAngles(SLICES, 4, 0)
        expect(sliceHoverOffset(angles[0], true, 0)).toEqual({ dx: 0, dy: 0 })
    })

    it('offsets along the slice bisector when hovered', () => {
        const angles = computeSliceAngles(SLICES, 4, 0)
        const { dx, dy } = sliceHoverOffset(angles[0], true, 10)
        // Midpoint angle π/4 — offset is (cos π/4, sin π/4) * 10
        expect(dx).toBeCloseTo(Math.cos(Math.PI / 4) * 10)
        expect(dy).toBeCloseTo(Math.sin(Math.PI / 4) * 10)
    })
})
