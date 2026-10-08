import { useActions, useValues } from 'kea'

import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
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
    const canEdit =
        node?.type !== 'metric' &&
        userHasAccess(
            AccessControlResourceType.WarehouseObjects,
            AccessControlLevel.Editor,
            savedQuery?.user_access_level
        )

    return (
        <>
            <SceneTitleSection
                name={node?.name}
                nameSuffix={typeTag && <LemonTag type={typeTag.type}>{typeTag.label}</LemonTag>}
                actions={
                    // A failed saved query never resolves on its own, so the placeholder must not
                    // outlive it. The Materialization and Query tabs carry the retry.
                    node && savedQuery ? (
                        <NodeDetailActions node={node} savedQuery={savedQuery} />
                    ) : node?.saved_query_id && !savedQueryError ? (
                        <LemonSkeleton className="h-8 w-56" />
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
