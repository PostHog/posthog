import { useActions, useValues } from 'kea'

import { Button, Item, ItemContent, ItemDescription, Kbd, KbdGroup } from '@posthog/quill'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { dataCatalogNewMetricSceneLogic } from '../dataCatalogNewMetricSceneLogic'
import { NEW_METRIC_SQL_QUERY_KEY, SQL_PLACEHOLDER, SQL_VALIDATION_DEBOUNCE_MS } from './NewMetricSqlDefinition'
import { QuillMetricFormField } from './QuillMetricFormField'
import { QuillSqlTestResult } from './QuillSqlTestResult'

function SqlErrorCallout({ message }: { message: string }): JSX.Element {
    return (
        <Item variant="outline" size="sm" tone="destructive">
            <ItemContent>
                <ItemDescription>{message}</ItemDescription>
            </ItemContent>
        </Item>
    )
}

export function QuillNewMetricSqlDefinition({ onAddUnit }: { onAddUnit: () => void }): JSX.Element {
    const {
        metricForm,
        sqlSourceQuery,
        sqlPreview,
        sqlPreviewLoading,
        sqlPreviewError,
        sqlPreviewStale,
        sqlValidationMessage,
    } = useValues(dataCatalogNewMetricSceneLogic)
    const { testSqlQuery, setSqlEditorError, setSqlMetadata, setSqlMetadataLoading, openInSqlEditor } =
        useActions(dataCatalogNewMetricSceneLogic)

    const testDisabledReason = !metricForm.sql.trim()
        ? 'Write a query before testing it'
        : (sqlValidationMessage ?? undefined)

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
                        onMetadata={setSqlMetadata}
                        onMetadataLoading={setSqlMetadataLoading}
                        metadataDebounceMs={SQL_VALIDATION_DEBOUNCE_MS}
                        metadataFreshSources
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
            {sqlValidationMessage && <SqlErrorCallout message={sqlValidationMessage} />}
            {sqlPreviewError && !sqlValidationMessage ? (
                <SqlErrorCallout message={sqlPreviewError} />
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
