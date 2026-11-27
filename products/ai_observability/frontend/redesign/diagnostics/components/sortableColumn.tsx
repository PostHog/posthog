import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'

import { SortHeader } from './SortHeader'

export interface SortableColumnOptions<Order extends string> {
    /** The order the list is sorted by, or null before the list knows it. */
    order: Order | null
    onOrder: (order: Order) => void
    'data-attr': string
}

/** Builds the key and title of the columns a diagnostics list sorts by, one per API order. */
export function sortableColumn<Row extends Record<string, any>, Order extends string>({
    order,
    onOrder,
    'data-attr': dataAttr,
}: SortableColumnOptions<Order>): (
    label: string,
    key: Order
) => Pick<LemonTableColumn<Row, undefined>, 'title' | 'key'> {
    return (label, key) => ({
        key,
        title: (
            <SortHeader
                label={label}
                active={order === key}
                onSort={() => onOrder(key)}
                // pinned: autocapture dashboards and tests select the sort headers by this value
                data-attr={`${dataAttr}-order-${key}`}
            />
        ),
    })
}
