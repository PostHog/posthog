export const METRIC_NAME_REGEX = /^[A-Za-z][A-Za-z0-9_]*$/

/** Values typed in the new metric modal, carried into the SQL editor's "Save as metric" dialog. */
export interface MetricFormPrefill {
    name?: string
    display_name?: string
    description?: string
    unit?: string
}

export const METRIC_FIELD_COPY = {
    name: { label: 'Name', placeholder: 'monthly_active_users' },
    displayName: { label: 'Display name', placeholder: 'Monthly active users' },
    description: { label: 'Description', placeholder: 'What this metric measures and how to read it' },
    unit: { label: 'Unit', placeholder: 'users' },
} as const

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

// Mirrors MAX_MARKDOWN_DEFINITION_LENGTH enforced in products/data_catalog/backend/logic/validation.py.
export const METRIC_MARKDOWN_MAX_LENGTH = 20000

// Mirrors METRIC_BULK_MAX enforced in products/data_catalog/backend/logic/metrics.py.
export const METRIC_BULK_MAX = 100

export function metricCount(count: number): string {
    return `${count} ${count === 1 ? 'metric' : 'metrics'}`
}

export function validateMetricDescription(description: string): string | undefined {
    if (description.length > METRIC_DESCRIPTION_MAX_LENGTH) {
        return `Keep the description under ${METRIC_DESCRIPTION_MAX_LENGTH} characters. Say what the metric means in a few sentences.`
    }
    return undefined
}
