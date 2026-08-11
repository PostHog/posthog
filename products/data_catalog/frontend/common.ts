export const METRIC_NAME_REGEX = /^[A-Za-z][A-Za-z0-9_]*$/

export function humanizeDefinitionKind(kind: string | null): string {
    if (!kind) {
        return 'Stub'
    }
    if (kind === 'HogQLQuery') {
        return 'SQL'
    }
    if (kind === 'MarkdownDefinition') {
        return 'Markdown'
    }
    return kind
}

export function validateMetricName(name: string): string | undefined {
    if (!name) {
        return 'Name is required'
    }
    if (!METRIC_NAME_REGEX.test(name)) {
        return 'Use letters, numbers, and underscores, starting with a letter'
    }
    return undefined
}

// Mirrors MAX_DESCRIPTION_LENGTH enforced in products/data_catalog/backend/logic/validation.py.
export const METRIC_DESCRIPTION_MAX_LENGTH = 1000

export function validateMetricDescription(description: string): string | undefined {
    if (description.length > METRIC_DESCRIPTION_MAX_LENGTH) {
        return `Keep the description under ${METRIC_DESCRIPTION_MAX_LENGTH} characters. Say what the metric means in a few sentences.`
    }
    return undefined
}
