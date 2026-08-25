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
        rowCount: 2,
    }

    const TRIGGER = '[data-attr="dashboard-insight-visualization-picker"]'

    const openPicker = async (container: HTMLElement): Promise<void> => {
        const trigger = container.querySelector(TRIGGER)
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
        const persistVisualizationType = jest.fn()
        const { container } = render(
            <SqlVisualizationPicker
                query={query}
                {...twoColumnData}
                persistVisualizationType={persistVisualizationType}
            />
        )

        await openPicker(container)
        await pick('Line chart')

        const [display, chartSettings] = persistVisualizationType.mock.calls[0]
        expect(display).toEqual(ChartDisplayType.ActionsLineGraph)
        expect(chartSettings.xAxis).toEqual({ column: 'day' })
        expect(chartSettings.yAxis.map((series: any) => series.column)).toEqual(['total'])
    })

    // Auto is the first option and resolves to a real chart, so it needs axes like the type it
    // resolves to. Without them the chart draws with blank x labels.
    it('gives Auto the axes of the chart it resolves to', async () => {
        const persistVisualizationType = jest.fn()
        const { container } = render(
            <SqlVisualizationPicker
                query={query}
                {...twoColumnData}
                persistVisualizationType={persistVisualizationType}
            />
        )

        await openPicker(container)
        await pick('Auto (Line chart)')

        const [display, chartSettings] = persistVisualizationType.mock.calls[0]
        expect(display).toEqual(ChartDisplayType.Auto)
        expect(chartSettings.xAxis).toEqual({ column: 'day' })
        expect(chartSettings.yAxis.map((series: any) => series.column)).toEqual(['total'])
    })

    it('keeps axes the insight already has, when they still name plottable columns', async () => {
        const persistVisualizationType = jest.fn()
        const alreadyAxed = {
            ...query,
            chartSettings: { xAxis: { column: 'day' }, yAxis: [{ column: 'total' }] },
        } as DataVisualizationNode
        const { container } = render(
            <SqlVisualizationPicker
                query={alreadyAxed}
                {...twoColumnData}
                persistVisualizationType={persistVisualizationType}
            />
        )

        await openPicker(container)
        await pick('Line chart')

        const [, chartSettings] = persistVisualizationType.mock.calls[0]
        expect(chartSettings.xAxis).toEqual({ column: 'day' })
        expect(chartSettings.yAxis.map((series: any) => series.column)).toEqual(['total'])
    })

    // The editor drops axes whose y series is not a numeric column and re-seeds. Keeping them would
    // save a chart the tile cannot draw.
    it('repairs axes whose y series is no longer a numeric column', async () => {
        const persistVisualizationType = jest.fn()
        const stale = {
            ...query,
            chartSettings: { xAxis: { column: 'total' }, yAxis: [{ column: 'day' }] },
        } as DataVisualizationNode
        const { container } = render(
            <SqlVisualizationPicker
                query={stale}
                {...twoColumnData}
                persistVisualizationType={persistVisualizationType}
            />
        )

        await openPicker(container)
        await pick('Line chart')

        const [, chartSettings] = persistVisualizationType.mock.calls[0]
        expect(chartSettings.xAxis).toEqual({ column: 'day' })
        expect(chartSettings.yAxis.map((series: any) => series.column)).toEqual(['total'])
    })

    it('shows the pick immediately rather than waiting for the save to land', async () => {
        const { container } = render(
            <SqlVisualizationPicker query={query} {...twoColumnData} persistVisualizationType={jest.fn()} />
        )

        await openPicker(container)
        await pick('Pie chart')

        expect(container.querySelector('[data-attr="dashboard-insight-visualization-picker"]')).toHaveTextContent(
            'Pie chart'
        )
    })

    // Reported four times in review: without this the select keeps showing a type the insight does
    // not have, and because LemonSelect suppresses onChange for an unchanged value, re-picking that
    // same type does nothing. The user cannot recover without a reload.
    it('falls back to the saved type when a save settles without landing, so the pick can be retried', async () => {
        const persistVisualizationType = jest.fn()
        const { container, rerender } = render(
            <SqlVisualizationPicker
                query={query}
                {...twoColumnData}
                persistVisualizationType={persistVisualizationType}
            />
        )

        await openPicker(container)
        await pick('Pie chart')
        expect(container.querySelector(TRIGGER)).toHaveTextContent('Pie chart')

        // The save goes out, then settles without the saved query changing — what a failure looks like.
        rerender(
            <SqlVisualizationPicker
                query={query}
                {...twoColumnData}
                saving
                persistVisualizationType={persistVisualizationType}
            />
        )
        rerender(
            <SqlVisualizationPicker
                query={query}
                {...twoColumnData}
                saving={false}
                persistVisualizationType={persistVisualizationType}
            />
        )

        expect(container.querySelector(TRIGGER)).toHaveTextContent('Table')
    })
})
