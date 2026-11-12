import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { DotMatrixColumnMapping } from '../Accounts/DotMatrixColumnMapping'
import { getMatrixHogQLScope } from '../Accounts/dotMatrixHogQLScope'
import { getActivityHogQLBindings } from '../ProductActivity/activityHogQLBindings'
import { ActivityQueryActions } from '../ProductActivity/ActivityQueryActions'
import { ActivityQueryEditor } from '../ProductActivity/ActivityQueryEditor'
import { productUsageGridLogic } from './productUsageGridLogic'

export function ProductUsageQueryEditor(): JSX.Element {
    const {
        draftKind,
        queryDraft,
        mappingDraft,
        result,
        loading,
        querySaveError,
        saveError,
        controls,
        customerAnalyticsConfig,
    } = useValues(productUsageGridLogic)
    const { setQueryDraft, setMappingDraft, runQuery, saveSource, cancelEditor } = useActions(productUsageGridLogic)
    const bindings = getActivityHogQLBindings({
        accounts: result?.accounts.results ?? [],
        dateRange: controls.dateRange,
        groupTypeIndex: customerAnalyticsConfig?.account_group_type_index,
    })
    const scope = getMatrixHogQLScope(queryDraft)
    const columns = result?.hogql?.columns ?? []
    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="product-activity-query-editor">
            {draftKind === 'hogql' ? (
                <>
                    <ActivityQueryEditor
                        queryKey="product-activity-book"
                        query={queryDraft}
                        bindings={bindings}
                        helpText="Use {filters} on events to apply the account filters and date range. For warehouse tables, use {account_external_ids} with IN and your own date condition. {account_ids} contains Customer analytics account IDs."
                        scopeWarning={
                            !scope.usesFilters && !scope.usesAccountIds && !scope.usesAccountExternalIds
                                ? 'This query has no account placeholder. Check that its WHERE clause limits results to the intended accounts.'
                                : undefined
                        }
                        onChange={setQueryDraft}
                        onRun={runQuery}
                    />
                    {columns.length > 0 && (
                        <DotMatrixColumnMapping columns={columns} mapping={mappingDraft} onChange={setMappingDraft} />
                    )}
                </>
            ) : (
                <p className="mb-0">Load the configured PostHog product usage rules for the filtered accounts.</p>
            )}
            <ActivityQueryActions
                loading={loading}
                runError={draftKind === 'hogql' && !queryDraft.trim() ? 'Enter a query.' : undefined}
                saveError={querySaveError}
                onRun={runQuery}
                onSave={saveSource}
                onCancel={cancelEditor}
                dataAttributes={{ run: 'product-activity-run', save: 'product-activity-save' }}
            />
            <p className="text-xs text-secondary mb-0">Saved sources are private to your account in this browser.</p>
            {saveError && <LemonBanner type="error">{saveError}</LemonBanner>}
        </div>
    )
}
