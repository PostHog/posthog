import { format } from 'sql-formatter'

export function formatHogQL(sql: string): string {
    if (!sql.trim()) {
        return sql
    }
    try {
        return format(sql, {
            language: 'postgresql',
            keywordCase: 'upper',
            identifierCase: 'preserve',
            dataTypeCase: 'upper',
            functionCase: 'lower',
            indentStyle: 'standard',
            tabWidth: 4,
            useTabs: false,
            linesBetweenQueries: 1,
        })
    } catch {
        return sql
    }
}
