import { render } from '@testing-library/react'

import { ExportedInsight } from '~/exporter/ExportedInsight/ExportedInsight'
import { SharingConfigurationSettings } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightModel } from '~/types'

// The legend's internal rows need scene/router wiring that the exporter doesn't provide in isolation;
// we only care here about WHERE the legend lands relative to the chart, so render a marker instead.
jest.mock('lib/components/InsightLegend/InsightLegend', () => ({
    InsightLegend: ({ horizontal }: { horizontal?: boolean }) => (
        <div data-testid="legend" data-horizontal={String(!!horizontal)} />
    ),
}))
// Render the chart as a marker too — the real Query mounts logics we don't need for placement.
jest.mock('~/queries/Query/Query', () => ({
    Query: () => <div data-testid="chart" />,
}))

const trendsLineInsight = require('../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json') as InsightModel

beforeEach(() => {
    initKeaTests()
})

function renderExported(legendPosition?: string): HTMLElement {
    const source = (trendsLineInsight as any).query.source
    const insight = {
        ...trendsLineInsight,
        query: {
            ...(trendsLineInsight as any).query,
            source: {
                ...source,
                trendsFilter: { ...source.trendsFilter, ...(legendPosition ? { legendPosition } : {}) },
            },
        },
    } as InsightModel

    const exportOptions = { legend: true } as SharingConfigurationSettings

    const { container } = render(<ExportedInsight insight={insight} themes={[]} exportOptions={exportOptions} />)
    return container
}

describe('ExportedInsight legend position', () => {
    it('places a vertical legend after the chart when position is unset (defaults to right)', () => {
        const container = renderExported()

        const chart = container.querySelector('[data-testid="chart"]')!
        const legend = container.querySelector('[data-testid="legend"]')!
        expect(chart).not.toBeNull()
        expect(legend).not.toBeNull()
        // vertical (side) legend
        expect(legend.getAttribute('data-horizontal')).toBe('false')
        // legend comes after the chart in document order -> right side
        expect(chart.compareDocumentPosition(legend) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })

    it('places a horizontal legend below the chart when position is bottom', () => {
        const container = renderExported('bottom')

        const chart = container.querySelector('[data-testid="chart"]')!
        const legend = container.querySelector('[data-testid="legend"]')!
        // horizontal legend
        expect(legend.getAttribute('data-horizontal')).toBe('true')
        // legend after the chart -> below
        expect(chart.compareDocumentPosition(legend) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })

    it('places a horizontal legend before the chart when position is top', () => {
        const container = renderExported('top')

        const chart = container.querySelector('[data-testid="chart"]')!
        const legend = container.querySelector('[data-testid="legend"]')!
        expect(legend.getAttribute('data-horizontal')).toBe('true')
        // legend before the chart -> above
        expect(chart.compareDocumentPosition(legend) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
    })
})
