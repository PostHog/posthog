import { IconChevronRight, IconDatabase } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DataModelingNodeType } from '~/types'

import { NODE_TYPE_TAG_SETTINGS } from './nodeStyles'

const LEGEND_ENTRIES: { type: DataModelingNodeType; description: string }[] = [
    { type: 'view', description: 'A virtual table based on a SQL query' },
    { type: 'matview', description: 'A persisted view with improved query performance' },
    { type: 'endpoint', description: 'A materialized endpoint for API access' },
]

export interface NodeTypeLegendProps {
    collapsed: boolean
    onToggleCollapse: () => void
}

/** Explains what each node color and shape on the canvas means. */
export function NodeTypeLegend({ collapsed, onToggleCollapse }: NodeTypeLegendProps): JSX.Element {
    return (
        <div className="bg-surface-primary border rounded shadow-sm max-w-64">
            <LemonButton
                size="xsmall"
                fullWidth
                onClick={onToggleCollapse}
                data-attr="lineage-legend-toggle"
                sideIcon={<IconChevronRight className={collapsed ? '' : 'rotate-90'} />}
            >
                <span className="text-xs font-semibold text-secondary">Node types</span>
            </LemonButton>
            {!collapsed && (
                <div className="flex flex-col gap-2 px-2 pb-2">
                    {LEGEND_ENTRIES.map(({ type, description }) => {
                        const { label, color } = NODE_TYPE_TAG_SETTINGS[type]
                        return (
                            <div key={type} className="flex gap-2 items-start">
                                {/* eslint-disable-next-line react/forbid-dom-props */}
                                <IconDatabase className="text-base shrink-0 mt-0.5" style={{ color }} />
                                <div className="min-w-0">
                                    <div className="text-xs font-semibold">{label}</div>
                                    <div className="text-xs text-secondary text-balance">{description}</div>
                                </div>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
