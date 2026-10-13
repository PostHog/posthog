import { IconGraph, IconPencil, IconPlay, IconServer } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet/CodeSnippet'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { METRIC_MARKDOWN_MAX_LENGTH } from '../common'
import { definitionField } from '../dataCatalogMetricSceneLogic'
import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { MetricMarkdownEditorField } from './MetricMarkdownEditorField'
import { RunMetricWithAIButton } from './RunMetricWithAIButton'
import { Section } from './Section'

export interface DataCatalogMetricRunResult {
    results?: unknown
    instructions?: string | null
    compiled_query?: string | null
}

export function MetricDefinition({
    metric,
    editingDefinition,
    draftMarkdown,
    saving,
    runResult,
    runResultLoading,
    onDraftMarkdown,
    onEdit,
    onStartEditingMarkdown,
    onSaveMarkdown,
    onRun,
    onRunWithAI,
    runWithAIDisabledReason,
}: {
    metric: DataCatalogMetricApi
    editingDefinition: boolean
    draftMarkdown: string
    saving: boolean
    runResult: DataCatalogMetricRunResult | null
    runResultLoading: boolean
    onDraftMarkdown: (value: string) => void
    onEdit: (editing: boolean) => void
    onStartEditingMarkdown: () => void
    onSaveMarkdown: (markdown: string) => void
    onRun: () => void
    onRunWithAI: () => void
    runWithAIDisabledReason?: string
}): JSX.Element {
    const kind = metric.definition_kind
    const sql = definitionField(metric, 'query')

    const runButton = (
        <LemonButton
            type="primary"
            size="small"
            icon={<IconPlay />}
            loading={runResultLoading}
            disabledReason={kind ? undefined : 'This metric has no runnable definition yet'}
            onClick={onRun}
        >
            Run metric
        </LemonButton>
    )
    const results = runResult ? <RunResult runResult={runResult} /> : null

    const sourceInsightButton = metric.source_insight_short_id ? (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconGraph />}
            to={urls.insightView(metric.source_insight_short_id as InsightShortId)}
        >
            View source insight
        </LemonButton>
    ) : null

    if (kind === 'HogQLQuery') {
        return (
            <Section title="Definition">
                <CodeSnippet language={Language.SQL}>{sql}</CodeSnippet>
                <div className="flex gap-2">
                    {runButton}
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconServer />}
                        to={urls.sqlEditor({ source: 'metric', metricName: metric.name })}
                    >
                        Open in SQL editor
                    </LemonButton>
                    {sourceInsightButton}
                </div>
                {results}
            </Section>
        )
    }

    if (kind === 'MarkdownDefinition') {
        return (
            <Section title="Definition">
                {editingDefinition ? (
                    <MarkdownDefinitionEditor
                        draftMarkdown={draftMarkdown}
                        saving={saving}
                        onDraftMarkdown={onDraftMarkdown}
                        onSave={onSaveMarkdown}
                        onCancel={() => onEdit(false)}
                    />
                ) : (
                    <>
                        <LemonMarkdown disableImages>
                            {definitionField(metric, 'markdown') || '_No instructions yet._'}
                        </LemonMarkdown>
                        <div className="flex gap-2">
                            <RunMetricWithAIButton onRun={onRunWithAI} disabledReason={runWithAIDisabledReason} />
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPencil />}
                                onClick={() => onEdit(true)}
                            >
                                Edit
                            </LemonButton>
                        </div>
                        {/* No run result here: the envelope only echoes the definition above, and the
                            agent reports the number in the side panel. */}
                    </>
                )}
            </Section>
        )
    }

    if (!kind) {
        return (
            <Section title="Definition">
                {editingDefinition ? (
                    <MarkdownDefinitionEditor
                        draftMarkdown={draftMarkdown}
                        saving={saving}
                        onDraftMarkdown={onDraftMarkdown}
                        onSave={onSaveMarkdown}
                        onCancel={() => onEdit(false)}
                    />
                ) : (
                    <LemonBanner type="info">
                        This metric is a stub with no definition. Add one to make it runnable.
                        <div className="flex gap-2 mt-2">
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={urls.sqlEditor({ source: 'metric', metricName: metric.name })}
                            >
                                Write SQL
                            </LemonButton>
                            <LemonButton type="secondary" size="small" onClick={onStartEditingMarkdown}>
                                Write markdown
                            </LemonButton>
                        </div>
                    </LemonBanner>
                )}
            </Section>
        )
    }

    return (
        <Section title="Definition">
            {sourceInsightButton ? (
                <p className="text-secondary">
                    This metric is derived from an insight. Edit the query in the insight, then refresh the metric.
                </p>
            ) : (
                <>
                    <p className="text-secondary">
                        This metric was created from a query definition and has no linked insight. Run it to see the
                        current results.
                    </p>
                    <LemonCollapse
                        panels={[
                            {
                                key: 'definition',
                                header: 'View definition',
                                content: (
                                    <CodeSnippet language={Language.JSON}>
                                        {JSON.stringify(metric.definition, null, 2)}
                                    </CodeSnippet>
                                ),
                            },
                        ]}
                    />
                </>
            )}
            <div className="flex gap-2">
                {runButton}
                {sourceInsightButton}
            </div>
            {results}
        </Section>
    )
}

function MarkdownDefinitionEditor({
    draftMarkdown,
    saving,
    onDraftMarkdown,
    onSave,
    onCancel,
}: {
    draftMarkdown: string
    saving: boolean
    onDraftMarkdown: (value: string) => void
    onSave: (markdown: string) => void
    onCancel: () => void
}): JSX.Element {
    const saveDisabledReason = !draftMarkdown.trim()
        ? 'Add the markdown definition'
        : draftMarkdown.length > METRIC_MARKDOWN_MAX_LENGTH
          ? `Keep the definition under ${METRIC_MARKDOWN_MAX_LENGTH} characters`
          : undefined

    return (
        <>
            <MetricMarkdownEditorField value={draftMarkdown} onChange={onDraftMarkdown} />
            <div className="flex gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    loading={saving}
                    disabledReason={saveDisabledReason}
                    onClick={() => onSave(draftMarkdown)}
                >
                    Save
                </LemonButton>
                <LemonButton type="secondary" size="small" onClick={onCancel}>
                    Cancel
                </LemonButton>
            </div>
        </>
    )
}

function RunResult({ runResult }: { runResult: DataCatalogMetricRunResult }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {runResult.instructions ? (
                <LemonMarkdown disableImages>{runResult.instructions}</LemonMarkdown>
            ) : (
                <ResultsTable results={runResult.results} />
            )}
            {runResult.compiled_query && (
                <LemonCollapse
                    panels={[
                        {
                            key: 'compiled',
                            header: 'Compiled query',
                            content: <CodeSnippet language={Language.SQL}>{runResult.compiled_query}</CodeSnippet>,
                        },
                    ]}
                />
            )}
        </div>
    )
}

function ResultsTable({ results }: { results: unknown }): JSX.Element {
    const rows = Array.isArray(results) ? results : []
    if (rows.length === 0) {
        return <p className="text-secondary">No results.</p>
    }
    const first = rows[0]
    if (first && typeof first === 'object' && !Array.isArray(first)) {
        const keys = Object.keys(first as Record<string, unknown>)
        return (
            <LemonTable
                dataSource={rows as Record<string, unknown>[]}
                columns={keys.map((columnKey) => ({
                    title: columnKey,
                    key: columnKey,
                    render: (_: unknown, row: Record<string, unknown>) => formatCell(row[columnKey]),
                }))}
                size="small"
            />
        )
    }
    return <CodeSnippet language={Language.JSON}>{JSON.stringify(results, null, 2)}</CodeSnippet>
}

function formatCell(value: unknown): string {
    if (value == null) {
        return ''
    }
    return typeof value === 'object' ? JSON.stringify(value) : String(value)
}
