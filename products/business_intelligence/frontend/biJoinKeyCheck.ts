import { escapeRawPropertyAsHogQLIdentifier } from '~/queries/utils'
import { DataWarehouseViewLink } from '~/types'

export function joinKeyCheckQuery(join: DataWarehouseViewLink): string | null {
    if (
        !join.joining_table_name ||
        !join.joining_table_key ||
        !/^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*$/.test(join.joining_table_key)
    ) {
        return null
    }
    const table = join.joining_table_name.split('.').map(escapeRawPropertyAsHogQLIdentifier).join('.')
    const key = join.joining_table_key.split('.').map(escapeRawPropertyAsHogQLIdentifier).join('.')
    return `SELECT
    join_key,
    count(*) AS matching_rows
FROM (
    SELECT ${key} AS join_key
    FROM ${table}
)
GROUP BY join_key
HAVING count(*) > 1 OR isNull(join_key)
ORDER BY matching_rows DESC
LIMIT 100`
}
