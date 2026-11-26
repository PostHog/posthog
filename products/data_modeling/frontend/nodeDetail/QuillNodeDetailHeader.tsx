import { Badge, Skeleton } from '@posthog/quill'

import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ScenePanel, ScenePanelInfoSection } from '~/layout/scenes/SceneLayout'
import { TodayScenePinButton } from '~/layout/today/TodayScenePinButton'

import { NODE_TYPE_TAG_SETTINGS } from '../lineage/nodeStyles'
import { isAiWrittenDescription } from './nodeDescriptionState'
import { QuillNodeDetailActions } from './QuillNodeDetailActions'
import { useNodeDetailHeader } from './useNodeDetailHeader'

export function QuillNodeDetailHeader({ id }: { id: string }): JSX.Element {
    const { node, nodeLoading, savedQuery, savedQueryError, nodeType, canEdit, updateNodeDescription } =
        useNodeDetailHeader(id)

    return (
        <>
            <SceneTitleSection
                name={node?.name}
                nameAction={<TodayScenePinButton />}
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
