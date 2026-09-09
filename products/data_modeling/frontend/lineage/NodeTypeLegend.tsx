import { IconInfo } from '@posthog/icons'
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

/** Explains what each node color on the canvas means. */
export function NodeTypeLegend({ collapsed, onToggleCollapse }: NodeTypeLegendProps): JSX.Element {
    return (
        // The button comes last so it keeps the same spot on the canvas, and the panel opens above it.
        <div className="flex flex-col items-start gap-1">
            {!collapsed && (
                <div className="flex flex-col gap-2 p-2 max-w-64 bg-surface-primary border rounded shadow-sm">
                    <div className="text-xs font-semibold text-secondary">Node types</div>
                    {LEGEND_ENTRIES.map(({ type, description }) => {
                        return (
                            <div key={type} className="flex gap-2 items-baseline">
                                <NodeTypeTag type={type} />
                                <div className="text-xs text-secondary text-balance min-w-0">{description}</div>
                            </div>
                        )
                    })}
                </div>
            )}
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconInfo />}
                onClick={onToggleCollapse}
                tooltip={collapsed ? 'Show node types' : 'Hide node types'}
                data-attr="lineage-legend-toggle"
            />
        </div>
    )
}
