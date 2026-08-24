import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { SqlVisualizationPicker } from './SqlVisualizationPicker'

describe('SqlVisualizationPicker', () => {
    const query = {
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query: 'select day, total from events' },
        display: ChartDisplayType.ActionsTable,
    } as DataVisualizationNode

    const twoColumnData = {
        columns: ['day', 'total'],
        types: [
            ['day', 'DateTime'],
            ['total', 'UInt64'],
        ],
        results: [
            ['2026-01-01', 1],
            ['2026-01-02', 2],
        ],
    }

    const openPicker = async (container: HTMLElement): Promise<void> => {
        const trigger = container.querySelector('[data-attr="dashboard-insight-visualization-picker"]')
        await userEvent.click(trigger as HTMLElement)
    }

    // Picking "Line chart" only succeeds when the columns were parsed out of insightData, since the
    // option is disabled without two columns and one numeric. So this covers the parsing too.
    it('saves the picked chart type onto the insight query', async () => {
        const persistDisplayOptions = jest.fn()
        const { container } = render(
            <SqlVisualizationPicker
                query={query}
                insightData={twoColumnData}
                persistDisplayOptions={persistDisplayOptions}
            />
        )

        await openPicker(container)
        await userEvent.click(screen.getByText('Line chart'))

        expect(persistDisplayOptions).toHaveBeenCalledWith({
            ...query,
            display: ChartDisplayType.ActionsLineGraph,
        })
    })
})
