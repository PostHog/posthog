import { useActions, useValues } from 'kea'

import { Button, Item, ItemContent, ItemDescription, Kbd, KbdGroup } from '@posthog/quill'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { dataCatalogNewMetricSceneLogic } from '../dataCatalogNewMetricSceneLogic'
import { NEW_METRIC_SQL_QUERY_KEY, SQL_PLACEHOLDER } from './NewMetricSqlDefinition'
import { QuillMetricFormField } from './QuillMetricFormField'
import { QuillSqlTestResult } from './QuillSqlTestResult'

export function QuillNewMetricSqlDefinition({ onAddUnit }: { onAddUnit: () => void }): JSX.Element {
    const {
        metricForm,
        sqlSourceQuery,
        sqlPreview,
        sqlPreviewLoading,
        sqlPreviewError,
        sqlPreviewStale,
        sqlEditorError,
    } = useValues(dataCatalogNewMetricSceneLogic)
    const { testSqlQuery, setSqlEditorError, openInSqlEditor } = useActions(dataCatalogNewMetricSceneLogic)

    const testDisabledReason = !metricForm.sql.trim()
        ? 'Write a query before testing it'
        : (sqlEditorError ?? undefined)

    return (
        <div className="flex flex-col gap-2">
            <QuillMetricFormField name="sql">
                {({ value, onChange }) => (
                    <CodeEditorResizeable
                        language="hogQL"
                        value={value ?? ''}
                        onChange={(query) => onChange(query ?? '')}
                        queryKey={NEW_METRIC_SQL_QUERY_KEY}
                        sourceQuery={sqlSourceQuery}
                        onError={setSqlEditorError}
                        onPressCmdEnter={testSqlQuery}
                        options={{ placeholder: SQL_PLACEHOLDER }}
                        minHeight="10rem"
                        maxHeight="40vh"
                    />
                )}
            </QuillMetricFormField>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Button
                    variant="outline"
                    loading={sqlPreviewLoading}
                    disabledReason={testDisabledReason}
                    onClick={testSqlQuery}
                    data-attr="data-catalog-new-metric-test-query"
                >
                    Test query
                    <KbdGroup>
                        <Kbd>⌘</Kbd>
                        <Kbd>↵</Kbd>
                    </KbdGroup>
                </Button>
                <Button variant="default" onClick={openInSqlEditor} data-attr="data-catalog-new-metric-open-sql-editor">
                    Open in SQL editor
                </Button>
            </div>
            {sqlPreviewError ? (
                <Item variant="outline" size="sm" tone="destructive">
                    <ItemContent>
                        <ItemDescription>{sqlPreviewError}</ItemDescription>
                    </ItemContent>
                </Item>
            ) : sqlPreview ? (
                <QuillSqlTestResult
                    preview={sqlPreview}
                    unit={metricForm.unit}
                    stale={sqlPreviewStale}
                    loading={sqlPreviewLoading}
                    onAddUnit={onAddUnit}
                />
            ) : null}
        </div>
    )
}
