interface CapturedChart {
    config: { type: string; data: { labels: string[]; datasets: any[] }; options: any }
    canvas: HTMLCanvasElement
}

let capturedCharts: CapturedChart[] = []

export function resetCapturedCharts(): void {
    capturedCharts = []
}

export function getCapturedChartConfigs(): CapturedChart[] {
    return capturedCharts
}

class MockChart {
    static _instances: MockChart[] = []
    config: any
    canvas: HTMLCanvasElement
    data: any

    constructor(canvas: HTMLCanvasElement, config: any) {
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
    getElementsAtEventForMode(): any[] {
        return []
    }
}

function renderChartDOM(container: HTMLElement, config: any): void {
    const wrapper = document.createElement('div')
    wrapper.setAttribute('data-attr', 'chart-data')
    wrapper.setAttribute('data-type', config.type ?? '')

    const labelsEl = document.createElement('div')
    labelsEl.setAttribute('data-attr', 'chart-labels')
    for (const [i, label] of (config.data?.labels ?? []).entries()) {
        const span = document.createElement('span')
        span.setAttribute('data-attr', `label-${i}`)
        span.textContent = String(label)
        labelsEl.appendChild(span)
    }
    wrapper.appendChild(labelsEl)

    const datasetsEl = document.createElement('div')
    datasetsEl.setAttribute('data-attr', 'chart-datasets')
    for (const [i, ds] of (config.data?.datasets ?? []).entries()) {
        const dsEl = document.createElement('div')
        dsEl.setAttribute('data-attr', `dataset-${i}`)
        dsEl.setAttribute('data-label', ds.label ?? '')
        dsEl.setAttribute('data-hidden', String(ds.hidden ?? false))
        dsEl.setAttribute('data-count', String(ds.count ?? ''))
        dsEl.setAttribute('data-compare', String(ds.compare ?? false))
        dsEl.setAttribute('data-compare-label', ds.compare_label ?? '')
        dsEl.setAttribute('data-status', ds.status ?? '')
        for (const [j, v] of (ds.data ?? []).entries()) {
            const point = document.createElement('span')
            point.setAttribute('data-attr', `dataset-${i}-point-${j}`)
            point.setAttribute('data-value', String(v))
            dsEl.appendChild(point)
        }
        datasetsEl.appendChild(dsEl)
    }
    wrapper.appendChild(datasetsEl)

    container.appendChild(wrapper)
}

export const chartJsMock = {
    Chart: MockChart,
    defaults: { animation: false, plugins: { legend: { labels: { generateLabels: () => [] } } } },
    registerables: [],
    Tooltip: { positioners: {} as Record<string, any> },
}
