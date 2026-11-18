import { Meta, StoryObj } from '@storybook/react'

import { ResultMenu as ResultMenuComponent } from 'lib/components/ResultMenu/ResultMenu'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'

import { getBIDrillQueries, getBIDrillSelection } from './biDrilldown'
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
    const selection = getBIDrillSelection(config, {
        status: longLabel ? 'Awaiting confirmation from the payment provider' : 'paid',
        ...(previous ? { bi_comparison: 'Previous period' } : {}),
    })
    const queryUrl = urls.sqlEditor({ query: getBIDrillQueries(query, selection)!.rows })
    return (
        <div style={{ width: 520, height: 460 }}>
            <ResultMenuComponent
                selectedResult={selection.labels.map(({ name, value }) => `${name}: ${value}`).join(' · ')}
                caption={previous ? 'Comparison period' : 'Current period'}
                interaction={{ x: 260, y: 240 }}
                // Keep the visual preview open while the snapshot runner resizes the viewport.
                close={() => {}}
                actions={['View underlying rows', 'Open in SQL editor'].map((name) => ({
                    name,
                    className: '',
                    to: queryUrl,
                    onClick: () => {},
                }))}
            />
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
