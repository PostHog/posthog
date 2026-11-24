import { color as d3Color } from 'd3-color'

import { drawScatterMarkers } from './draw-scatter'

describe('drawScatterMarkers', () => {
    it.each([
        ['#3388cc', 1],
        ['#3388cc24', 36 / 255],
        ['rgba(51, 136, 204, 0.2)', 0.2],
    ])('preserves %s opacity in both the fill and outline', (color, opacity) => {
        const ctx = document.createElement('canvas').getContext('2d')!
        let fillOpacity = 0
        let strokeOpacity = 0
        const fill = jest.spyOn(ctx, 'fill').mockImplementation(() => {
            fillOpacity = d3Color(String(ctx.fillStyle))!.opacity
        })
        const stroke = jest.spyOn(ctx, 'stroke').mockImplementation(() => {
            strokeOpacity = d3Color(String(ctx.strokeStyle))!.opacity
        })

        drawScatterMarkers(ctx, [{ index: 0, seriesIndex: 0, x: 10, y: 10, radius: 4, color, shape: 'circle' }], 0.7)

        expect(fillOpacity).toBeCloseTo(opacity * 0.7)
        expect(strokeOpacity).toBeCloseTo(opacity)
        fill.mockRestore()
        stroke.mockRestore()
    })
})
