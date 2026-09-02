const INSIGHT_ID_ALIASES = ['id', 'insightId', 'insight_id', 'short_id', 'shortId'] as const

interface InsightToolTarget {
    id?: number
    short_id?: string
}

const normalizeInsightReference = (value: unknown): number | string | null => {
    if (typeof value === 'number' && Number.isSafeInteger(value) && value > 0) {
        return value
    }
    if (typeof value === 'string') {
        const normalizedValue = value.trim()
        if (!normalizedValue) {
            return null
        }
        if (/^\d+$/.test(normalizedValue)) {
            const numericValue = Number(normalizedValue)
            return Number.isSafeInteger(numericValue) && numericValue > 0 ? numericValue : null
        }
        return normalizedValue
    }
    return null
}

export const extractInsightToolReferences = (innerInput: Record<string, unknown>): Array<number | string> =>
    INSIGHT_ID_ALIASES.map((alias) => normalizeInsightReference(innerInput[alias])).filter(
        (reference): reference is number | string => reference !== null
    )

/**
 * Mirrors the backend's primary-key-first lookup without allowing a numeric short ID to target a
 * different insight in the client. A numeric value can therefore only name this insight by its ID;
 * non-numeric values can name it by its short ID. When multiple aliases are supplied, each must
 * resolve to this same insight.
 */
export const insightToolTargetsCurrentInsight = (
    innerInput: Record<string, unknown>,
    insight: InsightToolTarget
): boolean => {
    if (!insight.id || !insight.short_id) {
        return false
    }

    const references = INSIGHT_ID_ALIASES.map((alias) => innerInput[alias]).filter(
        (reference): reference is unknown => reference !== undefined && reference !== null
    )

    return (
        references.length > 0 &&
        references.every((reference) => {
            const normalizedReference = normalizeInsightReference(reference)
            return typeof normalizedReference === 'number'
                ? normalizedReference === insight.id
                : normalizedReference === insight.short_id
        })
    )
}
