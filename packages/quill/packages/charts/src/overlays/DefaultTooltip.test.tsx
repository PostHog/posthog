import { cleanup, screen } from '@testing-library/react'

import type { TooltipContext } from '../core/types'
import { makeOverlayContext, renderOverlayInChart } from '../testing'
import { DefaultTooltip } from './DefaultTooltip'

const SCALES = { x: () => 0, y: (v: number) => v, yTicks: () => [] }

const SERIES_DATA: TooltipContext['seriesData'] = [{ series: { key: 'a', label: 'A', data: [] }, value: 19402, color: '#000' }]
const CANVAS_BOUNDS = {
    x: 0,
    y: 0,
    width: 800,
    height: 400,
    top: 0,
    right: 800,
    bottom: 400,
    left: 0,
    toJSON: () => ({}),
} as DOMRect

function renderTooltip(valueFormatter?: (v: number) => string): void {
    const ctx: TooltipContext = {
        dataIndex: 0,
        label: 'When',
        seriesData: SERIES_DATA,
        position: { x: 0, y: 0 },
        hoverPosition: null,
        canvasBounds: CANVAS_BOUNDS,
        isPinned: false,
    }
    renderOverlayInChart(<DefaultTooltip {...ctx} valueFormatter={valueFormatter} />, makeOverlayContext(SCALES))
}

describe('DefaultTooltip', () => {
    afterEach(cleanup)

    it.each([
        ['default (no formatter)', undefined, (19402).toLocaleString(), null as string | null],
        ['custom valueFormatter', (v: number) => `${v}ms`, '19402ms', (19402).toLocaleString()],
    ])('formats values with %s', (_, formatter, expected, absent) => {
        renderTooltip(formatter)
        screen.getByText(expected)
        if (absent) {
            expect(screen.queryByText(absent)).toBeNull()
        }
    })
})
