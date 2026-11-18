import { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { BIConfig, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { DashboardTile } from '~/types'

import { biDashboardCrossFilterLogic } from './biDashboardCrossFilterLogic'
import { BIDashboardFilterBar } from './BIDashboardFilterBar'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'

const config: BIConfig = {
    ...DEFAULT_BI_CONFIG,
    source: { table: 'example_orders' },
    rows: [
        { id: 'country', name: 'Country', expression: 'country', type: 'string', source: { table: 'example_orders' } },
    ],
}
const query: BIVisualizationNode = { ...buildBIQuery(config)!.node, kind: NodeKind.BIVisualizationNode, config }
const tiles = [1, 2, 3].map((id) => ({
    id,
    color: null,
    layouts: {},
    insight: { query, name: 'Orders by country', short_id: `example-${id}` },
})) as unknown as DashboardTile[]

function FilterBarPreview({
    longLabel = false,
    noTargets = false,
}: {
    longLabel?: boolean
    noTargets?: boolean
}): JSX.Element {
    useEffect(() => {
        const logic = biDashboardCrossFilterLogic({ dashboardId: 777, tiles: noTargets ? tiles.slice(0, 1) : tiles })
        const unmount = logic.mount()
        logic.actions.selectMark(1, 'Orders by country', query, {
            country: longLabel ? 'A long country label that must fit beside other dashboard controls' : 'US',
        })
        return unmount
    }, [longLabel, noTargets])
    return (
        <div className="w-[520px] max-w-full p-3">
            <BIDashboardFilterBar dashboardId={777} />
        </div>
    )
}

const meta: Meta = {
    title: 'Products/Business intelligence/Dashboard filter bar',
    parameters: { testOptions: { waitForSelector: '[data-attr="bi-dashboard-filter-bar"]' } },
}
export default meta

export const Active: StoryObj = { render: () => <FilterBarPreview /> }
export const LongLabel: StoryObj = { render: () => <FilterBarPreview longLabel /> }
export const NoRelatedWorksheets: StoryObj = { render: () => <FilterBarPreview noTargets /> }
export const Quill: StoryObj = {
    parameters: { featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV] },
    render: () => <FilterBarPreview longLabel />,
}
