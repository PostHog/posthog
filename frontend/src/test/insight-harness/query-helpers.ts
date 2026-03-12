import { screen } from '@testing-library/react'

interface ChartDatasetResult {
    label: string
    data: number[]
}

function getChartDatasets(): ChartDatasetResult[] {
    const container = screen.getByTestId('chart-datasets')
    const datasetEls = container.querySelectorAll('[data-attr^="dataset-"]')

    return Array.from(datasetEls)
        .filter((el) => el.getAttribute('data-attr')?.match(/^dataset-\d+$/))
        .map((el) => {
            const points = el.querySelectorAll('[data-value]')
            return {
                label: el.getAttribute('data-label') ?? '',
                data: Array.from(points).map((p) => Number(p.getAttribute('data-value'))),
            }
        })
}

export function expectNoNaN(): void {
    for (const ds of getChartDatasets()) {
        for (let i = 0; i < ds.data.length; i++) {
            expect(ds.data[i]).not.toBeNaN()
        }
    }
}
