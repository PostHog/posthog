import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'

import { biDrilldownLogic } from './biDrilldownLogic'
import { BIDrilldownMenu } from './BIDrilldownMenu'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'

const meta: Meta = {
    title: 'Products/Business intelligence/Result menu',
    parameters: { layout: 'fullscreen', testOptions: { waitForSelector: '[data-attr="bi-result-menu"]' } },
}
export default meta

function ResultMenu({ previous = false, longLabel = false }: { previous?: boolean; longLabel?: boolean }): JSX.Element {
    const config = {
        ...DEFAULT_BI_CONFIG,
        source: { table: 'orders' },
        rows: [
            {
                id: 'status',
                name: 'Status',
                expression: 'status',
                type: 'string' as const,
                source: { table: 'orders' },
            },
        ],
    }
    const query: BIVisualizationNode = { ...buildBIQuery(config)!.node, kind: NodeKind.BIVisualizationNode, config }
    const logicProps = { key: 'result-menu-story', query, onFilterDashboard: (): void => {} }
    const { inspect, setInteraction } = useActions(biDrilldownLogic(logicProps))
    useOnMountEffect(() => {
        setInteraction({ x: 260, y: 240, clickCount: 1 })
        inspect({
            status: longLabel ? 'Awaiting confirmation from the payment provider' : 'paid',
            ...(previous ? { bi_comparison: 'Previous period' } : {}),
        })
    })
    return (
        <div style={{ width: 520, height: 460 }}>
            <BIDrilldownMenu logicProps={logicProps} />
        </div>
    )
}

export const CurrentPeriod: StoryObj = { render: () => <ResultMenu /> }
export const LongSelection: StoryObj = { render: () => <ResultMenu longLabel /> }
export const ComparisonPeriod: StoryObj = { render: () => <ResultMenu previous /> }
export const Quill: StoryObj = {
    parameters: { featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV] },
    render: () => <ResultMenu />,
}
