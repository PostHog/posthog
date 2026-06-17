import { cleanup, screen } from '@testing-library/react'

import type { TooltipContext } from '../core/types'
import { makeOverlayContext, renderOverlayInChart } from '../testing'
import { DefaultTooltip } from './DefaultTooltip'

const SCALES = { x: () => 0, y: (v: number) => v, yTicks: () => [] }

const SERIES_DATA: TooltipContext['seriesData'] = [{ series: { key: 'a', label: 'A', data: [] }, value: 19402, color: '#000' }]

function renderTooltip(props: Partial<TooltipContext> & { valueFormatter?: (v: number) => string }): void {
    const ctx = { label: 'When', seriesData: SERIES_DATA, ...props } as TooltipContext
    renderOverlayInChart(<DefaultTooltip {...ctx} valueFormatter={props.valueFormatter} />, makeOverlayContext(SCALES))
}

describe('DefaultTooltip', () => {
    afterEach(cleanup)

    it('formats values with toLocaleString by default', () => {
        renderTooltip({})
        expect(screen.getByText('19,402')).toBeTruthy()
    })

    it('formats values with a provided valueFormatter', () => {
        renderTooltip({ valueFormatter: (v) => `${v}ms` })
        expect(screen.getByText('19402ms')).toBeTruthy()
        expect(screen.queryByText('19,402')).toBeNull()
    })
})
