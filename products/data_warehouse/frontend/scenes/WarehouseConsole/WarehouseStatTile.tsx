import { Card, CardContent, Text } from '@posthog/quill'

import { WarehouseMeter, type WarehouseMeterProps } from './WarehouseMeter'

export interface WarehouseStatTileProps {
    label: string
    value: string
    /** One muted line under the value. */
    detail?: string
    /** A second muted line, for a caveat about the figure. */
    note?: string
    meter?: Omit<WarehouseMeterProps, 'label'>
    'data-attr'?: string
}

/** One figure: label, value, one muted detail line and an optional meter. Place tiles in a `WarehouseStatStrip`. */
export function WarehouseStatTile({
    label,
    value,
    detail,
    note,
    meter,
    'data-attr': dataAttr,
}: WarehouseStatTileProps): JSX.Element {
    return (
        <Card size="sm" className="h-full" data-attr={dataAttr}>
            <CardContent className="flex h-full min-w-0 flex-col gap-1 px-3">
                <Text size="xs" variant="muted" render={<div />}>
                    {label}
                </Text>
                <Text size="lg" weight="semibold" className="truncate tabular-nums" render={<div />}>
                    {value}
                </Text>
                {meter ? <WarehouseMeter {...meter} label={label} /> : null}
                {detail ? (
                    <Text size="xs" variant="muted" className="truncate" title={detail} render={<div />}>
                        {detail}
                    </Text>
                ) : null}
                {note ? (
                    <Text size="xs" variant="muted" render={<div />}>
                        {note}
                    </Text>
                ) : null}
            </CardContent>
        </Card>
    )
}
