import { LemonTable } from 'lib/lemon-ui/LemonTable'
import type { LemonTableProps } from 'lib/lemon-ui/LemonTable'

export type AlertingTableProps<T extends Record<string, any>> = LemonTableProps<T>

export function AlertingTable<T extends Record<string, any>>(props: AlertingTableProps<T>): JSX.Element {
    return <LemonTable {...props} size={props.size ?? 'small'} />
}
