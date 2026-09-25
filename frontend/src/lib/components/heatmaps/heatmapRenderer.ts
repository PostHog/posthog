import heatmapsJs, { Heatmap } from 'heatmap.js'

export const HEATMAP_CONFIG = { minOpacity: 0, maxOpacity: 0.8 }

export function createHeatmapRenderer(
    container: HTMLElement,
    options: { radius?: number; gradient?: Record<string, string> } = {}
): Heatmap<'value', 'x', 'y'> {
    return heatmapsJs.create({ ...HEATMAP_CONFIG, ...options, container })
}
