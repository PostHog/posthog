import type { MetricDefinitionType } from './dataCatalogNewMetricSceneLogic'

export const DEFINITION_TYPE_OPTIONS: { value: MetricDefinitionType; label: string }[] = [
    { value: 'sql', label: 'SQL' },
    { value: 'insight', label: 'Insight' },
    { value: 'markdown', label: 'Markdown' },
]

export const DEFINITION_TYPE_HINTS: Record<MetricDefinitionType, string> = {
    sql: 'Return the number. Agents and dashboards run this query.',
    insight: 'Use a saved insight. The metric copies its query.',
    markdown: 'Write the steps in words, for metrics that are not one query. Agents follow them.',
}

export function isMetricDefinitionType(value: string): value is MetricDefinitionType {
    return DEFINITION_TYPE_OPTIONS.some((option) => option.value === value)
}
