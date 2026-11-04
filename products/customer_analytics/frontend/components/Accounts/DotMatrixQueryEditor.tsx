import { useActions, useValues } from 'kea'
import { lazy, Suspense } from 'react'

import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { NodeKind } from '~/queries/schema/schema-general'

import type { accountDotMatrixTileLogic } from './accountDotMatrixTileLogic'
import { DotMatrixColumnMapping } from './DotMatrixColumnMapping'

const CodeEditor = lazy(async () => ({ default: (await import('lib/monaco/CodeEditor')).CodeEditor }))

export function DotMatrixQueryEditor({ logic }: { logic: ReturnType<typeof accountDotMatrixTileLogic> }): JSX.Element {
    const { queryDraft, mappingDraft, matrixResult, matrixResultLoading, querySaveError } = useValues(logic)
    const { setQueryDraft, setMappingDraft, runQuery, saveQuery, cancelQuery } = useActions(logic)
    const columns = matrixResult?.kind === 'hogql' ? (matrixResult.result.columns ?? []) : []
    const names = [...new Set(columns.filter((column): column is string => typeof column === 'string'))]
    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="account-dot-matrix-query-editor">
            <p className="text-secondary mb-0">
                {
                    'Use {filters} for this account and the selected weeks. {account_id} and {account_external_id} are also available. Your SQL controls which data appears.'
                }
            </p>
            <Suspense fallback={<Spinner />}>
                <CodeEditor
                    queryKey={`dot-matrix-${logic.props.instanceId}`}
                    language="hogQL"
                    height={200}
                    sourceQuery={{ kind: NodeKind.HogQLQuery, query: queryDraft }}
                    value={queryDraft}
                    onChange={(query) => setQueryDraft(query ?? '')}
                    onPressCmdEnter={runQuery}
                    options={{
                        minimap: { enabled: false },
                        wordWrap: 'on',
                        scrollBeyondLastLine: false,
                        automaticLayout: true,
                    }}
                />
            </Suspense>
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="primary"
                    onClick={runQuery}
                    loading={matrixResultLoading}
                    disabledReason={!queryDraft.trim() ? 'Enter a query.' : undefined}
                    data-attr="dot-matrix-run-query"
                >
                    Run query
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={saveQuery}
                    disabledReason={querySaveError}
                    data-attr="dot-matrix-save-query"
                >
                    Save source
                </LemonButton>
                <LemonButton type="tertiary" onClick={cancelQuery} data-attr="dot-matrix-cancel-query">
                    Cancel
                </LemonButton>
            </div>
            {matrixResult?.kind === 'hogql' && (
                <>
                    <DotMatrixColumnMapping columns={names} mapping={mappingDraft} onChange={setMappingDraft} />
                    {querySaveError && !matrixResultLoading && <LemonBanner type="info">{querySaveError}</LemonBanner>}
                </>
            )}
        </div>
    )
}
