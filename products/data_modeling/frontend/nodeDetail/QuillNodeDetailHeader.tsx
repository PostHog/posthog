import { useActions, useValues } from 'kea'

import { Badge, Skeleton } from '@posthog/quill'

import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ScenePanel, ScenePanelInfoSection } from '~/layout/scenes/SceneLayout'

import { NODE_TYPE_TAG_SETTINGS } from '../lineage/nodeStyles'
import { canEditNodeDescription, isAiWrittenDescription } from './nodeDescriptionState'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'
import { nodeTypeForDisplay } from './nodeTypeForDisplay'
import { QuillNodeDetailActions } from './QuillNodeDetailActions'

export function QuillNodeDetailHeader({ id }: { id: string }): JSX.Element {
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
    const nodeType = nodeTypeForDisplay(node, savedQuery)
    const canEdit = canEditNodeDescription(node, savedQuery)

    return (
        <>
            <SceneTitleSection
                name={node?.name}
                nameSuffix={
                    <span className="flex items-center gap-1">
                        {nodeType && <Badge>{NODE_TYPE_TAG_SETTINGS[nodeType].label}</Badge>}
                        {isAiWrittenDescription(node) && <Badge>AI-written description</Badge>}
                    </span>
                }
                actions={
                    node && savedQuery ? (
                        <QuillNodeDetailActions id={id} node={node} savedQuery={savedQuery} />
                    ) : node?.saved_query_id && !savedQueryError ? (
                        <Skeleton className="h-7 w-56" />
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
