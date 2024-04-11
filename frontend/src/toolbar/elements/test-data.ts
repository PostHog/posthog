import { HeatmapResponseType } from '../types'

export const testHeatmapData: HeatmapResponseType = {
    query: {
        width: 1280,
        height: 1000,
    },
    results: [
        { type: 'click', x: 10, y: 10, count: 100 },
        { type: 'click', x: 30, y: 33, count: 2 },
        { type: 'click', x: 980, y: 100, count: 1000 },
    ],
}
