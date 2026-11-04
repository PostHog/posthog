import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { NodeKind } from '~/queries/schema/schema-general'

import { DotMatrixColumnMapping } from '../Accounts/DotMatrixColumnMapping'
import { getMatrixHogQLScope } from '../Accounts/dotMatrixHogQLScope'
import { productUsageGridLogic } from './productUsageGridLogic'
const CodeEditor = lazyWithRetry(async () => ({ default: (await import('lib/monaco/CodeEditor')).CodeEditor }))

export function ProductUsageQueryEditor(): JSX.Element {
    const { draftKind, queryDraft, mappingDraft, result, loading, querySaveError, saveError } =
        useValues(productUsageGridLogic)
    const { setQueryDraft, setMappingDraft, runQuery, saveSource, cancelEditor } = useActions(productUsageGridLogic)
    const scope = getMatrixHogQLScope(queryDraft)
    const columns = result?.hogql?.columns ?? []
    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="product-activity-query-editor">
            {draftKind === 'hogql' ? (
                <>
                    <p className="text-secondary mb-0">
                        {
                            'Use {filters} on events to apply the account filters and date range. For warehouse tables, use {account_external_ids} with IN and your own date condition. {account_ids} contains Customer analytics account IDs.'
                        }
                    </p>
                    <Suspense fallback={<Spinner />}>
                        <CodeEditor
                            queryKey="product-activity-book"
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
                    {!scope.usesFilters && !scope.usesAccountIds && !scope.usesAccountExternalIds && (
                        <LemonBanner type="warning">
                            This query has no account placeholder. Check that its WHERE clause limits results to the
                            intended accounts.
                        </LemonBanner>
                    )}
                    {columns.length > 0 && (
                        <DotMatrixColumnMapping columns={columns} mapping={mappingDraft} onChange={setMappingDraft} />
                    )}
                </>
            ) : (
                <p className="mb-0">Load the configured PostHog product usage rules for the filtered accounts.</p>
            )}
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="primary"
                    loading={loading}
                    disabledReason={draftKind === 'hogql' && !queryDraft.trim() ? 'Enter a query.' : undefined}
                    onClick={runQuery}
                    data-attr="product-activity-run"
                >
                    Run query
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={saveSource}
                    disabledReason={querySaveError}
                    data-attr="product-activity-save"
                >
                    Save source
                </LemonButton>
                <LemonButton type="tertiary" onClick={cancelEditor}>
                    Cancel
                </LemonButton>
            </div>
            <p className="text-xs text-secondary mb-0">Saved sources are private to your account in this browser.</p>
            {saveError && <LemonBanner type="error">{saveError}</LemonBanner>}
        </div>
    )
}
