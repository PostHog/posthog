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
