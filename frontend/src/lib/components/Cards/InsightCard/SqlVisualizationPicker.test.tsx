import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { SqlVisualizationPicker, SqlVisualizationPickerProps } from './SqlVisualizationPicker'

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

    it('persists the chart type selected from the dashboard menu', async () => {
        const persistVisualizationType = jest.fn()
        const { container } = render(
            <SqlVisualizationPicker
                query={query}
                {...twoColumnData}
                persistVisualizationType={persistVisualizationType}
            />
        )

        await userEvent.click(container.querySelector(TRIGGER) as HTMLElement)
        const matches = screen.getAllByText('Line chart')
        await userEvent.click(matches[matches.length - 1])

        expect(persistVisualizationType).toHaveBeenCalledWith(ChartDisplayType.ActionsLineGraph)
    })

    it.each<[string, Pick<SqlVisualizationPickerProps, 'loading' | 'saving'>]>([
        ['fresh results are loading, even with cached columns', { loading: true }],
        ['the selected chart type is being saved', { saving: true }],
    ])('disables the picker while %s', (_label, state) => {
        const { container } = render(
            <SqlVisualizationPicker query={query} {...twoColumnData} {...state} persistVisualizationType={jest.fn()} />
        )

        expect(container.querySelector(TRIGGER)).toHaveAttribute('aria-disabled', 'true')
    })
})
