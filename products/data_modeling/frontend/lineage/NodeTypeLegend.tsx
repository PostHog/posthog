import { IconDatabase, IconInfo, IconX } from '@posthog/icons'
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

/** Legend for the node types the canvas draws. Grows upward, so its toggle never moves. */
export function NodeTypeLegend({ collapsed, onToggleCollapse }: NodeTypeLegendProps): JSX.Element {
    if (collapsed) {
        return (
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconInfo />}
                onClick={onToggleCollapse}
                data-attr="lineage-legend-toggle"
                tooltip="Show what each node type means"
            />
        )
    }

    return (
        <div className="flex flex-col gap-2 p-3 w-72 bg-surface-primary border rounded shadow-sm">
            <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-secondary">Node types</span>
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    onClick={onToggleCollapse}
                    data-attr="lineage-legend-toggle"
                    tooltip="Hide the legend"
                />
            </div>
            {LEGEND_ENTRIES.map(({ type, description }) => (
                <div key={type} className="flex items-start gap-2">
                    <IconDatabase
                        className="text-xl shrink-0 mt-0.5"
                        // The canvas colors each node type; the legend must use the same hue.
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ color: NODE_TYPE_TAG_SETTINGS[type].color }}
                    />
                    <div className="flex flex-col">
                        <span className="font-semibold">{NODE_TYPE_TAG_SETTINGS[type].label}</span>
                        <span className="text-xs text-secondary">{description}</span>
                    </div>
                </div>
            ))}
        </div>
    )
}
