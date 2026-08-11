import { IncrementalField } from '~/types'

const isTimestampType = (field: IncrementalField): boolean => {
    const type = field.type || field.field_type
    return type === 'timestamp' || type === 'datetime' || type === 'date'
}

export interface ResolveIncrementalFieldOptions {
    /** Sync method the field will drive. An `append` sync never merges, so a monotonic integer
     *  primary key is a safe cursor there; a merge (`incremental`) sync needs a real update column. */
    syncType?: 'incremental' | 'append'
    /** Primary key columns the backend detected for the table, used for the append fallback. */
    detectedPrimaryKeys?: string[] | null
}

/**
 * Pick a default incremental cursor, or return undefined so the user must choose.
 *
 * Only a column with real update semantics qualifies automatically: a timestamp/date named like
 * `updated*` or `created*`. For append syncs a detected integer primary key also qualifies, since
 * new rows always carry a larger key. Anything else — an arbitrary date column, an unrelated
 * integer — is left unset on purpose: guessing there is how a sync silently freezes on a column
 * that never advances (a date-of-birth column, a static priority flag).
 */
export const resolveIncrementalField = (
    fields: IncrementalField[],
    options?: ResolveIncrementalFieldOptions
): IncrementalField | undefined => {
    const updatedAt = fields.find((field) => /^updated/i.test(field.label) && isTimestampType(field))
    if (updatedAt) {
        return updatedAt
    }
    const createdAt = fields.find((field) => /^created/i.test(field.label) && isTimestampType(field))
    if (createdAt) {
        return createdAt
    }
    if (options?.syncType === 'append' && options.detectedPrimaryKeys?.length) {
        const primaryKeys = options.detectedPrimaryKeys
        const primaryKey = fields.find((field) => primaryKeys.includes(field.field) && field.type === 'integer')
        if (primaryKey) {
            return primaryKey
        }
    }
    return undefined
}
