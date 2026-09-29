import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { dataNodeLogic } from '../../DataNode/dataNodeLogic'
import { DataVisualizationLogicProps, SideBarTab, dataVisualizationLogic } from '../dataVisualizationLogic'
import { SideBar } from './SideBar'

const query: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: { kind: NodeKind.HogQLQuery, query: 'SELECT day, revenue FROM events' },
    display: ChartDisplayType.Metric,
}

const response: HogQLQueryResponse = {
    columns: ['day', 'revenue'],
    types: [
        ['day', 'Date'],
        ['revenue', 'Float64'],
    ],
    results: [['2026-01-01', 100]],
    hogql: '',
    hasMore: false,
}

describe('SideBar', () => {
    afterEach(() => {
        cleanup()
    })

    it('shows the series tab when the selected tab is not supported by a metric', async () => {
        initKeaTests()
        const props: DataVisualizationLogicProps = {
            key: 'metric-sidebar',
            query,
            cachedResults: response,
            dataNodeCollectionId: 'metric-sidebar',
        }
        const dataNode = dataNodeLogic({
            key: props.key,
            query: query.source,
            cachedResults: response,
            dataNodeCollectionId: props.dataNodeCollectionId,
        })
        const logic = dataVisualizationLogic(props)
        dataNode.mount()
        logic.mount()
        logic.actions.setSideBarTab(SideBarTab.ConditionalFormatting)

        render(
            <BindLogic logic={dataVisualizationLogic} props={props}>
                <SideBar />
            </BindLogic>
        )

        expect(await screen.findByText('X-axis')).toBeInTheDocument()
        expect(screen.queryByText('Conditional formatting')).not.toBeInTheDocument()

        logic.unmount()
        dataNode.unmount()
    })
})
