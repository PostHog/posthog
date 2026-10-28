import { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'

import { BIDrilldownProps, biDrilldownLogic } from './biDrilldownLogic'
import { BIDrilldownModal } from './BIDrilldownModal'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'

const config = {
    ...DEFAULT_BI_CONFIG,
    source: { table: 'example_orders' },
    rows: [
        {
            id: 'status',
            name: 'Status',
            expression: 'status',
            type: 'string' as const,
            source: { table: 'example_orders' },
        },
    ],
}
const query: BIVisualizationNode = { ...buildBIQuery(config)!.node, kind: NodeKind.BIVisualizationNode, config }
const dashboardProps: BIDrilldownProps = {
    key: 'dashboard-exploration-story',
    query,
    onFilterDashboard: () => {},
    getDashboardFilterUrl: () => '/project/1/dashboard/1#bi_filter=example',
}

function ExploreResult({ filtering = true, total = false }: { filtering?: boolean; total?: boolean }): JSX.Element {
    const props = filtering ? dashboardProps : { ...dashboardProps, onFilterDashboard: undefined }
    useEffect(() => {
        const logic = biDrilldownLogic(props)
        const unmount = logic.mount()
        logic.actions.inspect(total ? { count: 42 } : { status: 'paid' })
        return unmount
    }, [filtering, total])
    return <BIDrilldownModal logicProps={props} />
}

const meta: Meta = {
    title: 'Products/Business intelligence/Dashboard exploration',
    parameters: { layout: 'fullscreen', testOptions: { waitForSelector: '[role="dialog"]' } },
}
export default meta
export const FilterDashboard: StoryObj = { render: () => <ExploreResult /> }
export const UnsupportedTotal: StoryObj = { render: () => <ExploreResult total /> }
export const WorksheetOnly: StoryObj = { render: () => <ExploreResult filtering={false} /> }
