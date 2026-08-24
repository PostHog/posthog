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
        result: [
            ['2026-01-01', 1],
            ['2026-01-02', 2],
        ],
    }

    const openPicker = async (container: HTMLElement): Promise<void> => {
        const trigger = container.querySelector('[data-attr="dashboard-insight-visualization-picker"]')
        await userEvent.click(trigger as HTMLElement)
    }

    // The label also appears on the trigger once picked, so always take the most recent match.
    const pick = async (label: string): Promise<void> => {
        const matches = screen.getAllByText(label)
        await userEvent.click(matches[matches.length - 1])
    }

    // Picking "Line chart" only succeeds when the columns were parsed out of insightData, since the
    // option is disabled without two columns and one numeric. So this covers the parsing too.
    it('saves the picked chart type with axes, so a table saved without them still draws', async () => {
        const persistDisplayOptions = jest.fn()
        const { container } = render(
            <SqlVisualizationPicker query={query} {...twoColumnData} persistDisplayOptions={persistDisplayOptions} />
        )

        await openPicker(container)
        await pick('Line chart')

        expect(persistDisplayOptions).toHaveBeenCalledWith({
            ...query,
            display: ChartDisplayType.ActionsLineGraph,
            chartSettings: { xAxis: { column: 'day' }, yAxis: [{ column: 'total' }] },
        })
    })

    // Auto is the first option and resolves to a real chart, so it needs axes like the type it
    // resolves to. Without them the chart draws with blank x labels.
    it('gives Auto the axes of the chart it resolves to', async () => {
        const persistDisplayOptions = jest.fn()
        const { container } = render(
            <SqlVisualizationPicker query={query} {...twoColumnData} persistDisplayOptions={persistDisplayOptions} />
        )

        await openPicker(container)
        await pick('Auto (Line chart)')

        expect(persistDisplayOptions).toHaveBeenCalledWith({
            ...query,
            display: ChartDisplayType.Auto,
            chartSettings: { xAxis: { column: 'day' }, yAxis: [{ column: 'total' }] },
        })
    })

    it('keeps axes the insight already has', async () => {
        const persistDisplayOptions = jest.fn()
        const alreadyAxed = {
            ...query,
            chartSettings: { xAxis: { column: 'total' }, yAxis: [{ column: 'day' }] },
        } as DataVisualizationNode
        const { container } = render(
            <SqlVisualizationPicker
                query={alreadyAxed}
                {...twoColumnData}
                persistDisplayOptions={persistDisplayOptions}
            />
        )

        await openPicker(container)
        await pick('Line chart')

        expect(persistDisplayOptions).toHaveBeenCalledWith({
            ...alreadyAxed,
            display: ChartDisplayType.ActionsLineGraph,
        })
    })

    it('shows the pick immediately rather than waiting for the save to land', async () => {
        const { container } = render(
            <SqlVisualizationPicker query={query} {...twoColumnData} persistDisplayOptions={jest.fn()} />
        )

        await openPicker(container)
        await pick('Pie chart')

        expect(container.querySelector('[data-attr="dashboard-insight-visualization-picker"]')).toHaveTextContent(
            'Pie chart'
        )
    })
})
