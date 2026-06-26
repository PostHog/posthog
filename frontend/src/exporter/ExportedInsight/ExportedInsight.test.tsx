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
    // position → orientation ('true' = horizontal, for top/bottom) and whether the legend sits
    // before the chart in document order (top/left) vs after it (bottom/right). Covers all four
    // positions plus the unset default, which falls back to 'right'.
    it.each([
        ['unset (defaults to right)', undefined, 'false', 'after'],
        ['right', 'right', 'false', 'after'],
        ['left', 'left', 'false', 'before'],
        ['bottom', 'bottom', 'true', 'after'],
        ['top', 'top', 'true', 'before'],
    ])('places the legend correctly when position is %s', (_desc, position, horizontal, order) => {
        const container = renderExported(position)

        const chart = container.querySelector('[data-testid="chart"]')!
        const legend = container.querySelector('[data-testid="legend"]')!
        expect(chart).not.toBeNull()
        expect(legend).not.toBeNull()
        expect(legend.getAttribute('data-horizontal')).toBe(horizontal)
        const relation = order === 'before' ? Node.DOCUMENT_POSITION_PRECEDING : Node.DOCUMENT_POSITION_FOLLOWING
        expect(chart.compareDocumentPosition(legend) & relation).toBeTruthy()
    })
})
