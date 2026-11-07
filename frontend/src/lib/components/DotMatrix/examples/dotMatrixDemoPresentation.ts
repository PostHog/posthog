import type { DotMatrixCountBin } from '../types'
import {
    DOT_MATRIX_MOCK_PRODUCTS,
    DOT_MATRIX_PRODUCT_COUNT_SCALE,
    DOT_MATRIX_USER_COUNT_SCALE,
} from './dotMatrixMockFixtures'
import type { DotMatrixMockDatasetName } from './dotMatrixMockTypes'

export interface DotMatrixDemoPresentation {
    countScale: DotMatrixCountBin[]
    trendColor: string
    legend: { itemLabel: string; valueLabel: string; countLabel: string }
}

export function getDotMatrixDemoPresentation(
    datasetName: DotMatrixMockDatasetName,
    selectedSeries: string[]
): DotMatrixDemoPresentation {
    if (datasetName === 'ci') {
        return {
            countScale: DOT_MATRIX_PRODUCT_COUNT_SCALE,
            trendColor: '#36a352',
            legend: { itemLabel: 'job', valueLabel: 'Failures', countLabel: 'Failing jobs' },
        }
    }
    const countLabel = !selectedSeries.length
        ? 'Products used'
        : selectedSeries.length === 1
          ? `Users of ${DOT_MATRIX_MOCK_PRODUCTS.find(([key]) => key === selectedSeries[0])?.[1] ?? selectedSeries[0]}`
          : `Users of any of these ${selectedSeries.length} products`
    return {
        countScale: selectedSeries.length ? DOT_MATRIX_USER_COUNT_SCALE : DOT_MATRIX_PRODUCT_COUNT_SCALE,
        trendColor: selectedSeries.length ? '#3b76d4' : '#36a352',
        legend: {
            itemLabel: 'product',
            valueLabel: datasetName === 'people' ? 'Events' : 'Users',
            countLabel,
        },
    }
}
