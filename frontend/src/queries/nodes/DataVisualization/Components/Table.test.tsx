import { render } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { dataNodeLogic } from '../../DataNode/dataNodeLogic'
import { DataVisualizationLogicProps, dataVisualizationLogic } from '../dataVisualizationLogic'
import { Table } from './Table'

// Prevent loadData from completing so the response set via setResponse is not overwritten
jest.mock('~/queries/query', () => ({
    ...jest.requireActual('~/queries/query'),
    performQuery: jest.fn().mockImplementation(() => new Promise(() => {})),
}))

const dataNodeCollectionId = 'test-dataviz-table'
let logicCounter = 0

const query: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: `SELECT number AS n, tuple('__hx_tag', 'Sparkline', 'data', arrayMap(x -> (number + x) % 10, range(14))) AS trend FROM numbers(500)`,
    },
    display: ChartDisplayType.ActionsTable,
}

function sparklineResponse(rowCount: number): Record<string, any> {
    return {
        columns: ['n', 'trend'],
        types: [
            ['n', 'UInt64'],
            ['trend', 'Tuple(String, String, String, Array(UInt16))'],
        ] as [string, string][],
        results: Array.from({ length: rowCount }, (_, index) => [
            index,
            ['__hx_tag', 'Sparkline', 'data', Array.from({ length: 14 }, (_, x) => (index + x) % 10)],
        ]),
    }
}

function setup(rowCount: number): HTMLElement {
    logicCounter += 1
    const key = `test-dataviz-table-${logicCounter}`
    const props: DataVisualizationLogicProps = { key, query, dataNodeCollectionId }
    const dataNodeProps = { key, query: query.source, dataNodeCollectionId }

    const logic = dataVisualizationLogic(props)
    logic.mount()
    dataNodeLogic(dataNodeProps).actions.setResponse(sparklineResponse(rowCount))

    const { container } = render(
        <Provider>
            <BindLogic logic={dataNodeLogic} props={dataNodeProps}>
                <BindLogic logic={dataVisualizationLogic} props={props}>
                    <Table uniqueKey={key} query={query} context={undefined} cachedResults={undefined} embedded />
                </BindLogic>
            </BindLogic>
        </Provider>
    )
    return container
}

describe('DataVisualization Table', () => {
    beforeEach(() => {
        initKeaTests()
        // jsdom has no layout — the virtualizer sizes its window from the scroll container's offset dimensions
        jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(600)
        jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('bounds mounted sparkline charts to the visible window for large results', () => {
        const container = setup(500)

        const sparklineCanvases = container.querySelectorAll('tbody canvas')
        expect(sparklineCanvases.length).toBeGreaterThan(0)
        expect(sparklineCanvases.length).toBeLessThan(40)
    })

    it('renders every row for small results without virtualization', () => {
        const container = setup(20)

        expect(container.querySelectorAll('tbody canvas')).toHaveLength(20)
        expect(container.querySelectorAll('.LemonTable__virtual-spacer')).toHaveLength(0)
    })
})
