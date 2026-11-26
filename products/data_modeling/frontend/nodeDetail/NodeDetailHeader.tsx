import { LemonSkeleton } from '@posthog/lemon-ui'
import { Skeleton } from '@posthog/quill'

import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ScenePanel, ScenePanelInfoSection } from '~/layout/scenes/SceneLayout'
import { TodayScenePinButton } from '~/layout/today/TodayScenePinButton'

import { NodeDetailActions } from './NodeDetailActions'
import { NodeDetailTitleTags } from './NodeDetailTitleTags'
import { useNodeDetailHeader } from './useNodeDetailHeader'

export function NodeDetailHeader({ id }: { id: string }): JSX.Element {
    const { node, nodeLoading, savedQuery, savedQueryError, nodeType, canEdit, updateNodeDescription } =
        useNodeDetailHeader(id)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return (
        <>
            <SceneTitleSection
                name={node?.name}
                nameAction={<TodayScenePinButton />}
                nameSuffix={<NodeDetailTitleTags nodeType={nodeType} node={node} />}
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
