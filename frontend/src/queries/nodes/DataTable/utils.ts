import { DataTableColumn, DataTableStringColumn } from '~/queries/schema'
import { PropertyFilterType } from '~/types'

export function normalizeDataTableColumns(input: (DataTableStringColumn | DataTableColumn)[]): DataTableColumn[] {
    return input.map((column) => {
        if (typeof column === 'string') {
            const [first, ...rest] = column.split('.')
            return {
                type: first as PropertyFilterType,
                key: rest.join('.'),
            }
        }
        return column
    })
}
