import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { getActivityHogQLBindings } from '../ProductActivity/activityHogQLBindings'
import { ActivityQueryActions } from '../ProductActivity/ActivityQueryActions'
import { ActivityQueryEditor } from '../ProductActivity/ActivityQueryEditor'
import type { accountDotMatrixTileLogic } from './accountDotMatrixTileLogic'
import { DotMatrixColumnMapping } from './DotMatrixColumnMapping'

export function DotMatrixQueryEditor({ logic }: { logic: ReturnType<typeof accountDotMatrixTileLogic> }): JSX.Element {
    const {
        queryDraft,
        mappingDraft,
        matrixResult,
        matrixResultLoading,
        querySaveError,
        queryScopeWarning,
        config,
        customerAnalyticsConfig,
        weekStartDay,
    } = useValues(logic)
    const { setQueryDraft, setMappingDraft, runQuery, saveQuery, cancelQuery } = useActions(logic)
    const bindings = getActivityHogQLBindings({
        accountId: logic.props.accountId,
        externalId: logic.props.externalId,
        groupTypeIndex: customerAnalyticsConfig?.account_group_type_index,
        weeks: config.weeks,
        weekStartDay,
    })
    const columns = matrixResult?.kind === 'hogql' ? (matrixResult.result.columns ?? []) : []
    const names = [...new Set(columns.filter((column): column is string => typeof column === 'string'))]
    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="account-dot-matrix-query-editor">
            <ActivityQueryEditor
                queryKey={`dot-matrix-${logic.props.instanceId}`}
                query={queryDraft}
                bindings={bindings}
                helpText="For events, put {filters} in WHERE to apply this account and the selected weeks. For warehouse and other tables, write your own account and date conditions. Compare your account column with {account_external_id}, the linked account key, or {account_id}, the Customer analytics account ID."
                scopeWarning={queryScopeWarning}
                onChange={setQueryDraft}
                onRun={runQuery}
            />
            <ActivityQueryActions
                loading={matrixResultLoading}
                runError={!queryDraft.trim() ? 'Enter a query.' : undefined}
                saveError={querySaveError}
                onRun={runQuery}
                onSave={saveQuery}
                onCancel={cancelQuery}
                dataAttributes={{
                    run: 'dot-matrix-run-query',
                    save: 'dot-matrix-save-query',
                    cancel: 'dot-matrix-cancel-query',
                }}
            />
            {matrixResult?.kind === 'hogql' && (
                <>
                    <DotMatrixColumnMapping columns={names} mapping={mappingDraft} onChange={setMappingDraft} />
                    {querySaveError && !matrixResultLoading && <LemonBanner type="info">{querySaveError}</LemonBanner>}
                </>
            )}
        </div>
    )
}
