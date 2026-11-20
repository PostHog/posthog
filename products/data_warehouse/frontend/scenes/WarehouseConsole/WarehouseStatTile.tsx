import { Card, CardContent, Progress, Text } from '@posthog/quill'

export interface WarehouseStatTileProps {
    label: string
    value: string
    /** Smaller line under the value. */
    detail?: string
    /** Extra detail line, such as the part of the figure that comes from failed queries. */
    note?: string
    /** A 0 to 100 meter under the figure. Values above 100 fill the bar. */
    meterPercent?: number | null
    meterVariant?: 'default' | 'warning' | 'destructive'
    'data-attr'?: string
}

export function WarehouseStatTile({
    label,
    value,
    detail,
    note,
    meterPercent,
    meterVariant = 'default',
    'data-attr': dataAttr,
}: WarehouseStatTileProps): JSX.Element {
    return (
        <Card size="sm" data-attr={dataAttr}>
            <CardContent className="flex min-w-0 flex-col gap-1">
                <Text size="xs" variant="muted" render={<div />}>
                    {label}
                </Text>
                <Text size="lg" weight="semibold" className="truncate" render={<div />}>
                    {value}
                </Text>
                {meterPercent != null && (
                    <Progress
                        value={Math.min(100, Math.max(0, meterPercent))}
                        variant={meterVariant}
                        aria-label={label}
                    />
                )}
                {detail && (
                    <Text size="xs" variant="muted" render={<div />}>
                        {detail}
                    </Text>
                )}
                {note && (
                    <Text size="xs" variant="muted" render={<div />}>
                        {note}
                    </Text>
                )}
            </CardContent>
        </Card>
    )
}
