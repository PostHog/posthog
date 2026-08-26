import { applyChartDefaults, DEFAULT_CHART_CONFIG } from './chart-config'

describe('applyChartDefaults', () => {
    it('applies the default chrome when no config is given', () => {
        expect(applyChartDefaults()).toEqual(DEFAULT_CHART_CONFIG)
    })

    it('lets a consumer value win over the default', () => {
        expect(applyChartDefaults({ showGrid: false }).showGrid).toBe(false)
    })

    it('falls back to the default for an explicitly undefined field', () => {
        expect(applyChartDefaults({ showGrid: undefined }).showGrid).toBe(true)
    })

    it('merges tooltip key by key, keeping placement when another tooltip field is set', () => {
        expect(applyChartDefaults({ tooltip: { enabled: false } }).tooltip).toEqual({
            placement: 'cursor',
            enabled: false,
        })
    })

    it('keeps the default placement when a consumer passes tooltip.placement as undefined', () => {
        expect(applyChartDefaults({ tooltip: { placement: undefined } }).tooltip?.placement).toBe('cursor')
    })
})
