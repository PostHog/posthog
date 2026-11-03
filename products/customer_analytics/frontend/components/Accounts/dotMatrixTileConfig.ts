import { type DotMatrixMockDatasetName } from 'lib/components/DotMatrix/examples/dotMatrixMockTypes'

import type { AccountViewTileConfig } from './accountViewTileConfig'

export interface DotMatrixTileConfig {
    dataset: DotMatrixMockDatasetName
    mode: 'dots' | 'count'
    selectedSeries: string[]
}

export function getDotMatrixTileConfig(config?: AccountViewTileConfig): DotMatrixTileConfig {
    const dataset = config?.dataset
    const selectedSeries = config?.selectedSeries
    return {
        dataset: dataset === 'product_activity' || dataset === 'ci' ? dataset : 'people',
        mode: config?.mode === 'count' ? 'count' : 'dots',
        selectedSeries:
            Array.isArray(selectedSeries) &&
            selectedSeries.length <= 64 &&
            selectedSeries.every((key) => typeof key === 'string' && key.length > 0 && key.length <= 128)
                ? [...new Set(selectedSeries)]
                : [],
    }
}
