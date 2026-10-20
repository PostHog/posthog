import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { biEditorLogic } from './biEditorLogic'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'
import { getBIVisualizationSource } from './biQueryResults'
import { BIResultSummary } from './BIResultSummary'
import { biSceneLogic } from './biSceneLogic'

beforeEach(() => {
    useMocks({
        post: {
            '/api/environments/:team_id/query/:kind/': {
                columns: ['count'],
                types: ['UInt64'],
                results: [[4]],
                tables: {},
            },
        },
    })
    initKeaTests()
})
afterEach(cleanup)

it('shows executed source property filters even with no worksheet filters and pending edits', async () => {
    const props = { tabId: 'property-filter-summary' }
    const logic = biSceneLogic(props)
    const unmount = logic.mount()
    const config = { ...DEFAULT_BI_CONFIG, source: { table: 'events' }, dateRange: { date_from: 'all' } }
    const query: BIVisualizationNode = { ...buildBIQuery(config)!.node, kind: NodeKind.BIVisualizationNode, config }
    query.source.filters = {
        dateRange: { date_from: 'all' },
        properties: [
            {
                key: 'channel',
                value: ['example-channel'],
                type: PropertyFilterType.Event,
                operator: PropertyOperator.Exact,
            },
        ],
    }
    logic.actions.restoreWorksheet(query)
    biEditorLogic(props).actions.setAutoUpdate(false)
    logic.actions.runQuery()
    await expectLogic(logic).toFinishAllListeners()
    const data = dataNodeLogic({
        key: logic.values.dataNodeKey,
        query: getBIVisualizationSource(logic.values.lastRunQuery!),
        autoLoad: true,
    })
    const unmountData = data.mount()
    await expectLogic(data).toFinishAllListeners()
    data.actions.loadDataSuccess({ columns: ['count'], types: ['UInt64'], results: [[4]] })
    biEditorLogic(props).actions.setDateRange({ date_from: '-7d' })
    render(<BIResultSummary {...props} />)
    expect(screen.getByText('Applied filters')).toBeInTheDocument()
    expect(screen.getByText('Source property filters')).toBeInTheDocument()
    expect(screen.getByText('channel = example-channel')).toBeInTheDocument()
    expect(screen.queryByText(/Date range:/)).not.toBeInTheDocument()
    unmountData()
    unmount()
})
