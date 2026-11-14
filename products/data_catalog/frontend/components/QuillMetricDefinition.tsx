import { IconGraph, IconPencil, IconPlay, IconServer } from '@posthog/icons'
import { Button, Collapsible, CollapsibleContent, CollapsibleTrigger, Text } from '@posthog/quill'

import { Language } from 'lib/components/CodeSnippet'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { definitionField } from '../dataCatalogMetricSceneLogic'
import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { NO_RUNNABLE_DEFINITION_REASON } from '../metricSceneActions'
import type { DataCatalogMetricRunResult } from './MetricDefinition'
import { QuillMarkdownDefinitionEditor } from './QuillMarkdownDefinitionEditor'
import { QuillMetricCallout } from './QuillMetricCallout'
import { QuillMetricCodeBlock, renderQuillMetricCodeBlock } from './QuillMetricCodeBlock'
import { QuillMetricRunResult } from './QuillMetricRunResult'
import { QuillRunMetricWithAIButton } from './QuillRunMetricWithAIButton'

export interface QuillMetricDefinitionProps {
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
}

export function QuillMetricDefinition({
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
}: QuillMetricDefinitionProps): JSX.Element {
    const kind = metric.definition_kind
    const sqlEditorUrl = urls.sqlEditor({ source: 'metric', metricName: metric.name })

    const runButton = (
        <Button
            variant="primary"
            loading={runResultLoading}
            disabledReason={kind ? undefined : NO_RUNNABLE_DEFINITION_REASON}
            onClick={onRun}
        >
            <IconPlay />
            Run metric
        </Button>
    )
    const results = runResult ? <QuillMetricRunResult runResult={runResult} /> : null
    const sourceInsightButton = metric.source_insight_short_id ? (
        <Button
            variant="outline"
            render={<LinkPrimitive to={urls.insightView(metric.source_insight_short_id as InsightShortId)} />}
        >
            <IconGraph />
            View source insight
        </Button>
    ) : null
    const markdownEditor = (
        <QuillMarkdownDefinitionEditor
            draftMarkdown={draftMarkdown}
            saving={saving}
            onDraftMarkdown={onDraftMarkdown}
            onSave={onSaveMarkdown}
            onCancel={() => onEdit(false)}
        />
    )

    if (kind === 'HogQLQuery') {
        return (
            <div className="flex flex-col gap-2">
                <QuillMetricCodeBlock code={definitionField(metric, 'query')} language={Language.SQL} />
                <div className="flex flex-wrap gap-2">
                    {runButton}
                    <Button variant="outline" render={<LinkPrimitive to={sqlEditorUrl} />}>
                        <IconServer />
                        Open in SQL editor
                    </Button>
                    {sourceInsightButton}
                </div>
                {results}
            </div>
        )
    }

    if (kind === 'MarkdownDefinition') {
        return (
            <div className="flex flex-col gap-2">
                {editingDefinition ? (
                    markdownEditor
                ) : (
                    <>
                        <LemonMarkdown disableImages renderCodeBlock={renderQuillMetricCodeBlock}>
                            {definitionField(metric, 'markdown') || '_No instructions yet._'}
                        </LemonMarkdown>
                        <div className="flex flex-wrap gap-2">
                            <QuillRunMetricWithAIButton onRun={onRunWithAI} disabledReason={runWithAIDisabledReason} />
                            <Button variant="outline" onClick={() => onEdit(true)}>
                                <IconPencil />
                                Edit
                            </Button>
                        </div>
                    </>
                )}
            </div>
        )
    }

    if (!kind) {
        return (
            <div className="flex flex-col gap-2">
                {editingDefinition ? (
                    markdownEditor
                ) : (
                    <QuillMetricCallout
                        tone="info"
                        actions={
                            <>
                                <Button variant="outline" render={<LinkPrimitive to={sqlEditorUrl} />}>
                                    Write SQL
                                </Button>
                                <Button variant="outline" onClick={onStartEditingMarkdown}>
                                    Write markdown
                                </Button>
                            </>
                        }
                    >
                        This metric is a stub with no definition. Add one to make it runnable.
                    </QuillMetricCallout>
                )}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {sourceInsightButton ? (
                <Text size="xs" variant="muted" className="m-0">
                    This metric is derived from an insight. Edit the query in the insight, then refresh the metric.
                </Text>
            ) : (
                <>
                    <Text size="xs" variant="muted" className="m-0">
                        This metric was created from a query definition and has no linked insight. Run it to see the
                        current results.
                    </Text>
                    <Collapsible>
                        <CollapsibleTrigger>View definition</CollapsibleTrigger>
                        <CollapsibleContent>
                            <QuillMetricCodeBlock
                                code={JSON.stringify(metric.definition, null, 2)}
                                language={Language.JSON}
                            />
                        </CollapsibleContent>
                    </Collapsible>
                </>
            )}
            <div className="flex flex-wrap gap-2">
                {runButton}
                {sourceInsightButton}
            </div>
            {results}
        </div>
    )
}
