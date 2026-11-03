import { isValidRE2, loadRE2 } from 'lib/utils/regexp'

export const getRegexFilterPatterns = (obj: unknown): string[] => {
    if (Array.isArray(obj)) {
        return obj.flatMap(getRegexFilterPatterns)
    }

    if (obj !== null && typeof obj === 'object') {
        const record = obj as Record<string, unknown>
        const nestedPatterns = Object.values(record).flatMap(getRegexFilterPatterns)
        if ((record.operator === 'regex' || record.operator === 'not_regex') && typeof record.value === 'string') {
            return [record.value, ...nestedPatterns]
        }
        return nestedPatterns
    }

    return []
}

export const hasInvalidRegexPattern = async (patterns: string[]): Promise<boolean> => {
    try {
        await loadRE2()
    } catch {
        // The backend checks the patterns too, so a stale or missing engine chunk must not block every regex query.
        return false
    }
    for (const pattern of patterns) {
        if (!(await isValidRE2(pattern))) {
            return true
        }
    }
    return false
}
