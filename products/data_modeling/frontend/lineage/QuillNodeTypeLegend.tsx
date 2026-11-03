import { IconDatabase, IconInfo, IconX } from '@posthog/icons'
import { Button, Card, CardContent, CardHeader, CardTitle, Text } from '@posthog/quill'

import { NODE_TYPE_TAG_SETTINGS, QUILL_NODE_TYPE_COLORS } from './nodeStyles'
import { LEGEND_ENTRIES, NodeTypeLegendProps } from './NodeTypeLegend'

export function QuillNodeTypeLegend({ collapsed, onToggleCollapse }: NodeTypeLegendProps): JSX.Element {
    if (collapsed) {
        return (
            <Button
                variant="outline"
                onClick={onToggleCollapse}
                tooltip="Show what each node type means"
                data-attr="lineage-legend-toggle"
            >
                <IconInfo />
                Node types
            </Button>
        )
    }

    return (
        <Card size="sm" className="w-72">
            <CardHeader className="flex flex-row items-center justify-between gap-2">
                <CardTitle>Node types</CardTitle>
                <Button
                    size="icon-sm"
                    onClick={onToggleCollapse}
                    aria-label="Hide the legend"
                    tooltip="Hide the legend"
                    data-attr="lineage-legend-toggle"
                >
                    <IconX />
                </Button>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
                {LEGEND_ENTRIES.map(({ type, description }) => (
                    <div key={type} className="flex items-start gap-2">
                        <IconDatabase
                            className="mt-0.5 shrink-0 text-xl"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ color: QUILL_NODE_TYPE_COLORS[type] }}
                        />
                        <div className="flex flex-col">
                            <Text size="xs" weight="semibold">
                                {NODE_TYPE_TAG_SETTINGS[type].label}
                            </Text>
                            <Text size="xs" variant="muted">
                                {description}
                            </Text>
                        </div>
                    </div>
                ))}
            </CardContent>
        </Card>
    )
}
