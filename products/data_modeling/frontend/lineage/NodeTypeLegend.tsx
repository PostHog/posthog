import { Fragment } from 'react'

import { IconChevronDown, IconChevronRight, IconInfo } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DataModelingNodeType } from '~/types'

import { NodeTypeTag } from './NodeTypeTag'

const LEGEND_ENTRIES: { type: DataModelingNodeType; description: string }[] = [
    { type: 'view', description: 'A virtual table based on a SQL query' },
    { type: 'matview', description: 'A persisted view with improved query performance' },
    { type: 'endpoint', description: 'A materialized endpoint for API access' },
]

export interface NodeTypeLegendProps {
    collapsed: boolean
    onToggleCollapse: () => void
}

/** Legend for the marks the canvas draws on each node. Grows upward, so its toggle never moves. */
export function NodeTypeLegend({ collapsed, onToggleCollapse }: NodeTypeLegendProps): JSX.Element {
    return (
        <div className="flex flex-col bg-surface-primary border rounded shadow-sm overflow-hidden">
            {!collapsed && (
                <div className="grid grid-cols-[max-content_1fr] items-center gap-x-2 gap-y-2 p-2 max-w-72">
                    {LEGEND_ENTRIES.map(({ type, description }) => (
                        <Fragment key={type}>
                            <span className="justify-self-start">
                                <NodeTypeTag type={type} />
                            </span>
                            <span className="text-xs text-secondary">{description}</span>
                        </Fragment>
                    ))}
                </div>
            )}
            <LemonButton
                size="small"
                fullWidth
                icon={<IconInfo />}
                sideIcon={collapsed ? <IconChevronRight /> : <IconChevronDown />}
                onClick={onToggleCollapse}
                data-attr="lineage-legend-toggle"
                tooltip={collapsed ? 'Show what each node type means' : 'Hide the legend'}
            >
                Node types
            </LemonButton>
        </div>
    )
}
