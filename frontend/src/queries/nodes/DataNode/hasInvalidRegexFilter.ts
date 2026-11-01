import { isValidRE2 } from 'lib/utils/regexp'

export const hasInvalidRegexFilter = (obj: unknown): boolean => {
    if (Array.isArray(obj)) {
        return obj.some(hasInvalidRegexFilter)
    }

    if (obj !== null && typeof obj === 'object') {
        const record = obj as Record<string, unknown>
        if (
            (record.operator === 'regex' || record.operator === 'not_regex') &&
            typeof record.value === 'string' &&
            !isValidRE2(record.value)
        ) {
            return true
        }

        return Object.values(record).some(hasInvalidRegexFilter)
    }

    return false
}
