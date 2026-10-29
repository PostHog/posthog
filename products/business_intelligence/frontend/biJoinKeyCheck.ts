import { escapeRawPropertyAsHogQLIdentifier } from '~/queries/utils'
import { DataWarehouseViewLink } from '~/types'

const fieldIdentifier =
    /[A-Za-z_$][\w$]*|"(?:[^"\\]|\\(?:[bBfFrRnNtT0aAvV\\"]|[xX][0-9a-fA-F]{2})|"")*"|`(?:[^`\\]|\\(?:[bBfFrRnNtT0aAvV\\']|[xX][0-9a-fA-F]{2})|``)*`/
const fieldReference = new RegExp(`^(?:${fieldIdentifier.source})(?:\\s*\\.\\s*(?:${fieldIdentifier.source}))*$`)

export function joinKeyCheckQuery(join: DataWarehouseViewLink): string | null {
    if (!join.joining_table_name || !join.joining_table_key || !fieldReference.test(join.joining_table_key)) {
        return null
    }
    const table = join.joining_table_name.split('.').map(escapeRawPropertyAsHogQLIdentifier).join('.')
    const key = join.joining_table_key
        .match(new RegExp(fieldIdentifier.source, 'g'))!
        .map((identifier) =>
            identifier.startsWith('"') || identifier.startsWith('`')
                ? identifier
                : escapeRawPropertyAsHogQLIdentifier(identifier)
        )
        .join('.')
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
