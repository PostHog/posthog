export interface ChartDataset {
    label?: string
    data?: number[]
    hidden?: boolean
    count?: number
    compare?: boolean
    compare_label?: string
    status?: string
    borderColor?: string
    backgroundColor?: string
    yAxisID?: string
}

export interface ChartScaleConfig {
    display?: boolean
    type?: string
    stacked?: boolean
    position?: string
    ticks?: { callback?: (value: number | string, index: number, values: unknown[]) => string }
}

export interface ChartConfig {
    type?: string
    data?: { labels?: string[]; datasets?: ChartDataset[] }
    options?: { scales?: Record<string, ChartScaleConfig>; [key: string]: unknown }
}

interface CapturedChart {
    config: ChartConfig
    canvas: HTMLCanvasElement
}

let capturedCharts: CapturedChart[] = []

export function resetCapturedCharts(): void {
    capturedCharts = []
    MockChart._instances = []
}

/** Returns all captured chart snapshots. The latest entry is always a live
 *  snapshot of the most recent MockChart instance so that callers see
 *  post-update data without needing a new Chart constructor call. */
export function getCapturedChartConfigs(): CapturedChart[] {
    return capturedCharts
}

const defaults: Record<string, unknown> = {
    animation: false,
    plugins: { legend: { labels: { generateLabels: () => [] } } },
}

class MockChart {
    static _instances: MockChart[] = []
    static defaults = defaults
    config: ChartConfig
    canvas: HTMLCanvasElement
    data: ChartConfig['data']

    constructor(canvas: HTMLCanvasElement, config: ChartConfig) {
        this.canvas = canvas
        this.config = config
        this.data = config.data
        MockChart._instances.push(this)
        capturedCharts.push({ config, canvas })

        const container = canvas.parentElement
        if (container) {
            renderChartDOM(container, config)
        }
    }

    static getChart(_canvas: HTMLCanvasElement): MockChart | undefined {
        return MockChart._instances.find((i) => i.canvas === _canvas)
    }

    static register(): void {}
    destroy(): void {
        MockChart._instances = MockChart._instances.filter((i) => i !== this)
    }
    update(): void {}
    resize(): void {}
    reset(): void {}
    stop(): void {}
    toBase64Image(): string {
        return ''
    }
    getElementsAtEventForMode(): unknown[] {
        return []
    }
}

function buildLabelsDOM(labels: string[]): HTMLDivElement {
    const el = document.createElement('div')
    el.setAttribute('data-attr', 'chart-labels')
    for (const [i, label] of labels.entries()) {
        const span = document.createElement('span')
        span.setAttribute('data-attr', `label-${i}`)
        span.textContent = String(label)
        el.appendChild(span)
    }
    return el
}

function buildDatasetDOM(ds: ChartDataset, index: number): HTMLDivElement {
    const el = document.createElement('div')
    el.setAttribute('data-attr', `dataset-${index}`)
    el.setAttribute('data-label', ds.label ?? '')
    el.setAttribute('data-hidden', String(ds.hidden ?? false))
    el.setAttribute('data-count', String(ds.count ?? ''))
    el.setAttribute('data-compare', String(ds.compare ?? false))
    el.setAttribute('data-compare-label', ds.compare_label ?? '')
    el.setAttribute('data-status', ds.status ?? '')
    for (const [j, v] of (ds.data ?? []).entries()) {
        const point = document.createElement('span')
        point.setAttribute('data-attr', `dataset-${index}-point-${j}`)
        point.setAttribute('data-value', String(v))
        el.appendChild(point)
    }
    return el
}

function renderChartDOM(container: HTMLElement, config: ChartConfig): void {
    const wrapper = document.createElement('div')
    wrapper.setAttribute('data-attr', 'chart-data')
    wrapper.setAttribute('data-type', config.type ?? '')

    wrapper.appendChild(buildLabelsDOM(config.data?.labels ?? []))

    const datasetsEl = document.createElement('div')
    datasetsEl.setAttribute('data-attr', 'chart-datasets')
    for (const [i, ds] of (config.data?.datasets ?? []).entries()) {
        datasetsEl.appendChild(buildDatasetDOM(ds, i))
    }
    wrapper.appendChild(datasetsEl)

    container.appendChild(wrapper)
}

export const Chart = MockChart
export { defaults }
export const registerables: unknown[] = []
export const Tooltip = { positioners: {} as Record<string, unknown> }
