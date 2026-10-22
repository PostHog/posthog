import posthog from 'posthog-js'

import type { Sorting } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api'

import type {
    DataCatalogMetricNameConflictApi,
    DataCatalogMetricNameConflictExistingApi,
} from './generated/api.schemas'

export const METRIC_NAME_REGEX = /^[A-Za-z][A-Za-z0-9_]*$/

export const HOGQL_METRIC_DEFINITION_KIND = 'HogQLQuery'

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
    if (kind === HOGQL_METRIC_DEFINITION_KIND) {
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
export const METRIC_DESCRIPTION_MAX_LENGTH = 300

// Mirrors MAX_MARKDOWN_DEFINITION_LENGTH enforced in products/data_catalog/backend/logic/validation.py.
export const METRIC_MARKDOWN_MAX_LENGTH = 20000

// Mirrors METRIC_BULK_MAX enforced in products/data_catalog/backend/logic/metrics.py.
export const METRIC_BULK_MAX = 100

export type DataCatalogTable = 'metrics' | 'relationships' | 'certifications'

export function compareText(a: string | null | undefined, b: string | null | undefined): number {
    return (a ?? '').localeCompare(b ?? '')
}

export function reportCatalogTableSorted(table: DataCatalogTable, sorting: Sorting | null): void {
    posthog.capture('data catalog table sorted', {
        table,
        column: sorting?.columnKey ?? null,
        order: sorting ? (sorting.order === 1 ? 'asc' : 'desc') : null,
    })
}

export function metricCount(count: number): string {
    return `${count} ${count === 1 ? 'metric' : 'metrics'}`
}

export function validateMetricDescription(description: string): string | undefined {
    if (description.length > METRIC_DESCRIPTION_MAX_LENGTH) {
        return `Keep the description under ${METRIC_DESCRIPTION_MAX_LENGTH} characters. Say what the number is in one or two sentences.`
    }
    return undefined
}

/** The metric that blocked a create because it holds the same name, or null for any other error. */
export function existingMetricFromNameConflict(error: unknown): DataCatalogMetricNameConflictExistingApi | null {
    if (!(error instanceof ApiError) || error.status !== 409 || error.code !== 'metric_name_taken') {
        return null
    }
    const body = error.data as DataCatalogMetricNameConflictApi | undefined
    return body?.extra?.existing_metric ?? null
}
