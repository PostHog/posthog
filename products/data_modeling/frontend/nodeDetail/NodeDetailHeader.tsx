import { useActions, useValues } from 'kea'

import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'
import { Skeleton } from '@posthog/quill'

import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ScenePanel, ScenePanelInfoSection } from '~/layout/scenes/SceneLayout'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { NODE_TYPE_TAG_SETTINGS } from '../lineage/nodeStyles'
import { NodeDetailActions } from './NodeDetailActions'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export function NodeDetailHeader({ id }: { id: string }): JSX.Element {
    const {
        node,
        nodeLoading,
        savedQuery: initialSavedQuery,
        savedQueryError,
    } = useValues(nodeDetailSceneLogic({ id }))
    const { updateNodeDescription } = useActions(nodeDetailSceneLogic({ id }))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const { savedQuery: currentSavedQuery } = useValues(
        materializationJobsLogic({
            viewId: node?.saved_query_id ?? '',
            kind: node?.type === 'endpoint' ? 'endpoint' : 'view',
        })
    )
    const savedQuery = currentSavedQuery ?? initialSavedQuery
    const nodeType =
        node?.type === 'view' || node?.type === 'matview'
            ? savedQuery
                ? savedQuery.is_materialized
                    ? 'matview'
                    : 'view'
                : node.type
            : node?.type
    const typeTag = nodeType ? NODE_TYPE_TAG_SETTINGS[nodeType] : null
    // A native table such as `events` has no warehouse table, so it has no annotation to edit.
    const isNativeTable = node?.type === 'table' && !node.warehouse_table_id
    const canEdit =
        node?.type !== 'metric' &&
        !isNativeTable &&
        userHasAccess(
            AccessControlResourceType.WarehouseObjects,
            AccessControlLevel.Editor,
            savedQuery?.user_access_level
        )

    return (
        <>
            <SceneTitleSection
                name={node?.name}
                nameSuffix={
                    <div className="flex items-center gap-1">
                        {typeTag && <LemonTag type={typeTag.type}>{typeTag.label}</LemonTag>}
                        {node?.description && node.description_source === 'ai_generated' && (
                            <LemonTag type="muted">AI-written description</LemonTag>
                        )}
                    </div>
                }
                actions={
                    // A failed saved query never resolves on its own, so the placeholder must not
                    // outlive it. The Materialization and Query tabs carry the retry.
                    node && savedQuery ? (
                        <NodeDetailActions id={id} node={node} savedQuery={savedQuery} />
                    ) : node?.saved_query_id && !savedQueryError ? (
                        todayRailNav ? (
                            <Skeleton className="h-8 w-56" />
                        ) : (
                            <LemonSkeleton className="h-8 w-56" />
                        )
                    ) : undefined
                }
                description={node?.description}
                resourceType={{ type: 'sql_editor' }}
                canEdit={canEdit}
                onDescriptionChange={canEdit ? (description) => updateNodeDescription(description) : undefined}
                isLoading={nodeLoading && !node}
                renameDebounceMs={500}
                saveOnBlur
            />
            <ScenePanel>
                <ScenePanelInfoSection>
                    {/* Take the date from the saved query, because the author next to it comes from
                        there too. A node backfilled from an existing saved query holds the date of
                        the backfill, so the two would describe different events. The node's own
                        date stands in only where there is no saved query. */}
                    <SceneActivityIndicator
                        prefix="Created"
                        at={node?.saved_query_id ? savedQuery?.created_at : node?.created_at}
                        by={savedQuery?.created_by}
                    />
                </ScenePanelInfoSection>
            </ScenePanel>
        </>
    )
}
