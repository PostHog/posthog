import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { dataCatalogNewMetricSceneLogic } from '../dataCatalogNewMetricSceneLogic'
import { SqlTestResult } from './SqlTestResult'

const NEW_METRIC_SQL_QUERY_KEY = 'data-catalog-new-metric'

const SQL_PLACEHOLDER = '-- e.g. SELECT count(DISTINCT person_id) FROM events WHERE timestamp > now() - INTERVAL 30 DAY'

export function NewMetricSqlDefinition({ onAddUnit }: { onAddUnit: () => void }): JSX.Element {
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
            <LemonField name="sql">
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
            </LemonField>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    loading={sqlPreviewLoading}
                    disabledReason={testDisabledReason}
                    onClick={testSqlQuery}
                    sideIcon={<span className="text-xs text-secondary">⌘↵</span>}
                    data-attr="data-catalog-new-metric-test-query"
                >
                    Test query
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={openInSqlEditor}
                    data-attr="data-catalog-new-metric-open-sql-editor"
                >
                    Open in SQL editor
                </LemonButton>
            </div>
            {sqlPreviewError ? (
                <LemonBanner type="error">{sqlPreviewError}</LemonBanner>
            ) : sqlPreview ? (
                <SqlTestResult
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
