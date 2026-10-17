import type { DataTableRow } from './dataTableLogic'

export function getRowExpansionKey(
    { result }: DataTableRow,
    rowIndex: number,
    columns: string[],
    isEventsQuery: boolean
): string | number {
    if (isEventsQuery) {
        const event = Array.isArray(result) ? result[columns.indexOf('*')] : result
        if (typeof event?.uuid === 'string' && event.uuid.trim()) {
            return event.uuid
        }
    }
    return rowIndex
}
