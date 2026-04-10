import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { dataNodeLogic } from '../../../DataNode/dataNodeLogic'
import { DataVisualizationLogicProps, dataVisualizationLogic } from '../../dataVisualizationLogic'
import { TwoDimensionalHeatmap } from './TwoDimensionalHeatmap'

// Prevent loadData from completing (success or failure) so Kea's loader never
// dispatches loadDataFailure and clears the response set via setResponse.
jest.mock('~/queries/query', () => ({
    ...jest.requireActual('~/queries/query'),
    performQuery: jest.fn().mockImplementation(() => new Promise(() => {})),
}))

const dataNodeCollectionId = 'new-test-SQL-heatmap'
let logicCounter = 0

const makeQuery = (nullLabel = '(header null)', nullValue = ''): DataVisualizationNode => ({
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: 'select 1',
    },
    display: ChartDisplayType.TwoDimensionalHeatmap,
    chartSettings: {
        heatmap: {
            xAxisColumn: 'region',
            yAxisColumn: 'segment',
            valueColumn: 'count',
            nullLabel,
            nullValue,
        },
    },
})

const response = {
    columns: ['region', 'segment', 'count'],
    types: [
        ['region', 'String'],
        ['segment', 'String'],
        ['count', 'Int64'],
    ] as [string, string][],
    results: [
        [null, 'Enterprise', 10],
        ['US', null, 20],
        ['US', 'Enterprise', null],
    ],
}

const setup = (nullLabel = '(header null)', nullValue = ''): ReturnType<typeof dataVisualizationLogic.build> => {
    logicCounter += 1
    const testKey = `test-two-dimensional-heatmap-${logicCounter}`
    const query = makeQuery(nullLabel, nullValue)
    const props: DataVisualizationLogicProps = {
        key: testKey,
        query,
        dataNodeCollectionId,
    }

    const logic = dataVisualizationLogic(props)
    logic.mount()
    dataNodeLogic({ key: testKey, query: query.source, dataNodeCollectionId }).actions.setResponse(response)

    render(
        <Provider>
            <BindLogic logic={dataVisualizationLogic} props={props}>
                <TwoDimensionalHeatmap />
            </BindLogic>
        </Provider>
    )

    return logic
}

describe('TwoDimensionalHeatmap', () => {
    afterEach(() => {
        cleanup()
    })

    beforeEach(() => {
        initKeaTests()
    })

    it('uses the null label in headers and the null value in cell contents', async () => {
        setup('(header null)', '(cell null)')

        expect(await screen.findAllByText('(header null)')).toHaveLength(2)
        expect(screen.getAllByText('(cell null)')).toHaveLength(2)
        expect(screen.queryByText(/^null$/)).not.toBeInTheDocument()
    })

    it('updates cell contents when the null value setting changes', async () => {
        const logic = setup('(header null)')

        await screen.findAllByText('(header null)')
        expect(screen.queryByText('(cell null)')).not.toBeInTheDocument()

        await act(async () => {
            logic.actions.updateChartSettings({
                heatmap: {
                    ...logic.values.chartSettings.heatmap,
                    nullValue: '(cell null)',
                },
            })
        })

        expect(await screen.findAllByText('(cell null)')).toHaveLength(2)
        expect(await screen.findAllByText('(header null)')).toHaveLength(2)
    })
})
