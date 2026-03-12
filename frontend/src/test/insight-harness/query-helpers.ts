import { screen } from '@testing-library/react'

export interface ChartDatasetResult {
    label: string
    data: number[]
    hidden: boolean
    compare: boolean
    compareLabel: string
    status: string
}

export function getChartDatasets(): ChartDatasetResult[] {
    const container = screen.getByTestId('chart-datasets')
    const datasetEls = container.querySelectorAll('[data-attr^="dataset-"]')

    return Array.from(datasetEls)
        .filter((el) => el.getAttribute('data-attr')?.match(/^dataset-\d+$/))
        .map((el) => {
            const points = el.querySelectorAll('[data-value]')
            return {
                label: el.getAttribute('data-label') ?? '',
                data: Array.from(points).map((p) => Number(p.getAttribute('data-value'))),
                hidden: el.getAttribute('data-hidden') === 'true',
                compare: el.getAttribute('data-compare') === 'true',
                compareLabel: el.getAttribute('data-compare-label') ?? '',
                status: el.getAttribute('data-status') ?? '',
            }
        })
}

export function getChartLabels(): string[] {
    const container = screen.getByTestId('chart-labels')
    const labelEls = container.querySelectorAll('[data-attr^="label-"]')
    return Array.from(labelEls).map((el) => el.textContent ?? '')
}

export function getDatasetsByLabel(labelMatch: string | RegExp): ChartDatasetResult[] {
    return getChartDatasets().filter((ds) =>
        typeof labelMatch === 'string' ? ds.label.includes(labelMatch) : labelMatch.test(ds.label)
    )
}

export function getVisibleDatasets(): ChartDatasetResult[] {
    return getChartDatasets().filter((ds) => !ds.hidden)
}

export function expectNoNaN(): void {
    for (const ds of getChartDatasets()) {
        for (let i = 0; i < ds.data.length; i++) {
            expect(ds.data[i]).not.toBeNaN()
        }
    }
}

export function getChartType(): string {
    return screen.getByTestId('chart-data').getAttribute('data-type') ?? ''
}

export function getGoalLines(): Array<{ value: number; label: string }> {
    const container = screen.queryByTestId('chart-goal-lines')
    if (!container) {
        return []
    }
    const goalEls = container.querySelectorAll('[data-attr^="goal-line-"]')
    return Array.from(goalEls).map((el) => ({
        value: Number(el.getAttribute('data-value')),
        label: el.getAttribute('data-label') ?? '',
    }))
}
