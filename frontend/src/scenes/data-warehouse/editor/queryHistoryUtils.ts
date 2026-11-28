import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

// The query as of this edit — what "Restore" loads back into the editor.
export function restorableQueryFromLog(logItem: HumanizedActivityLogItem): string | null {
    const change = logItem.unprocessed?.detail.changes?.find((c) => c.field === 'query' && extractQuery(c.after) !== '')
    return change ? extractQuery(change.after) : null
}

export function extractQuery(value: unknown): string {
    if (value && typeof value === 'object' && 'query' in value) {
        const query = (value as { query?: unknown }).query
        return typeof query === 'string' ? query : ''
    }
    return ''
}
