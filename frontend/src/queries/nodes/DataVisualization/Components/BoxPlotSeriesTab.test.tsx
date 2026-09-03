import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { dataNodeLogic } from '../../DataNode/dataNodeLogic'
import { DataVisualizationLogicProps, dataVisualizationLogic } from '../dataVisualizationLogic'
import { BoxPlotSeriesTab } from './BoxPlotSeriesTab'

const query: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: { kind: NodeKind.HogQLQuery, query: 'select * from summaries' },
    display: ChartDisplayType.BoxPlot,
    chartSettings: {
        boxPlot: {
            xAxisColumn: 'bucket',
            minColumn: 'min',
            p25Column: 'p25',
            medianColumn: 'median',
            meanColumn: 'mean',
            p75Column: 'p75',
            maxColumn: 'max',
        },
    },
}

const cachedResults: HogQLQueryResponse = {
    results: [['Mon', 1, 2, 3, 4, 5, 6, 0]],
    columns: ['bucket', 'min', 'p25', 'median', 'mean', 'p75', 'max', 'alternate_min'],
    types: [
        ['bucket', 'String'],
        ['min', 'Float64'],
        ['p25', 'Float64'],
        ['median', 'Float64'],
        ['mean', 'Float64'],
        ['p75', 'Float64'],
        ['max', 'Float64'],
        ['alternate_min', 'Float64'],
    ],
}

describe('BoxPlotSeriesTab', () => {
    it('shows box plot roles and saves a changed statistic column', async () => {
        initKeaTests()
        const setQuery = jest.fn()
        let currentQuery = query
        const props: DataVisualizationLogicProps = {
            key: 'box-plot-series-tab',
            query: currentQuery,
            cachedResults,
            dataNodeCollectionId: 'box-plot-series-tab',
            setQuery: (setter) => {
                currentQuery = setter(currentQuery)
                setQuery(currentQuery)
            },
        }

        dataNodeLogic({
            key: props.key,
            query: query.source,
            cachedResults,
            dataNodeCollectionId: props.dataNodeCollectionId,
        }).mount()
        dataVisualizationLogic(props).mount()

        const { container } = render(
            <BindLogic logic={dataVisualizationLogic} props={props}>
                <BoxPlotSeriesTab />
            </BindLogic>
        )

        expect(screen.getByText('25th percentile')).toBeInTheDocument()
        expect(screen.getByText('75th percentile')).toBeInTheDocument()

        const minimumSelect = container.querySelector('[data-attr="box-plot-minColumn"]')
        if (!(minimumSelect instanceof HTMLElement)) {
            throw new Error('Expected the minimum column selector')
        }

        const user = userEvent.setup()
        await user.click(minimumSelect)
        await user.click(await screen.findByText('alternate_min'))

        await waitFor(() => expect(currentQuery.chartSettings?.boxPlot?.minColumn).toBe('alternate_min'))

        const xAxisSelect = container.querySelector('[data-attr="box-plot-x-axis-column"]')
        if (!(xAxisSelect instanceof HTMLElement)) {
            throw new Error('Expected the X-axis column selector')
        }

        await user.click(xAxisSelect)
        const noneOption = (await screen.findAllByText('None')).find(
            (element) => !element.closest('[data-attr="box-plot-series-column"]')
        )
        if (!noneOption) {
            throw new Error('Expected the None option')
        }
        await user.click(noneOption)

        await waitFor(() => expect(currentQuery.chartSettings?.boxPlot?.xAxisColumn).toBeNull())
    })
})
