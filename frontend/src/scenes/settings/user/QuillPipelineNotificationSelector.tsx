import { Badge, Spinner, Text } from '@posthog/quill'

import { lockedDisabledReason } from '../shared/notificationLocks'
import { PIPELINE_HINT } from './emailPreferencesCopy'
import { PIPELINE_KIND_LABELS, PipelineItem, PipelineTeamGroup } from './pipelineNotificationsLogic'
import { QuillNotificationCheckbox } from './QuillNotificationCheckbox'
import { QuillNotificationSelector } from './QuillNotificationSelector'

export function QuillPipelineNotificationSelector({
    expanded,
    onExpandedChange,
    pipelines,
    pipelinesLoading,
    pipelinesByTeam,
    enforcedFor,
    isPipelineChecked,
    userLoading,
    onTogglePipeline,
    onEnableAll,
    onDisableAll,
}: {
    expanded: boolean
    onExpandedChange: (expanded: boolean) => void
    pipelines: PipelineItem[]
    pipelinesLoading: boolean
    pipelinesByTeam: Record<string, PipelineTeamGroup>
    enforcedFor: (teamId: number) => boolean | null
    isPipelineChecked: (pipelineId: string, enforced: boolean | null) => boolean
    userLoading: boolean
    onTogglePipeline: (pipelineId: string, enabled: boolean) => void
    onEnableAll: () => void
    onDisableAll: () => void
}): JSX.Element {
    return (
        <QuillNotificationSelector
            title="Select pipelines to receive notifications for"
            expanded={expanded}
            onExpandedChange={onExpandedChange}
            className="ps-9"
            hint={PIPELINE_HINT}
            bulkActions={
                pipelinesLoading || pipelines.length === 0
                    ? undefined
                    : {
                          enableLabel: 'Enable all notifications',
                          disableLabel: 'Mute all notifications',
                          onEnableAll,
                          onDisableAll,
                      }
            }
        >
            {pipelinesLoading ? (
                <div className="flex items-center gap-2 py-2">
                    <Spinner />
                    <Text size="xs" variant="muted" render={<span />}>
                        Loading pipelines...
                    </Text>
                </div>
            ) : pipelines.length === 0 ? (
                <Text size="xs" variant="muted" className="m-0">
                    No pipelines found in your projects.
                </Text>
            ) : (
                Object.entries(pipelinesByTeam).map(([key, { teamId, teamName, items }]) => {
                    const enforced = enforcedFor(teamId)

                    return (
                        <div key={key} className="flex flex-col gap-2">
                            <div className="flex flex-wrap items-center gap-2">
                                <Text size="xs" weight="medium" render={<span />}>
                                    {teamName}
                                </Text>
                                <Badge>{`id: ${teamId}`}</Badge>
                                {enforced !== null && <Badge variant="info">Set by your admin</Badge>}
                            </div>
                            <div className="flex flex-col gap-1 ps-4">
                                {items.map((pipeline) => (
                                    <QuillNotificationCheckbox
                                        key={pipeline.id}
                                        id={`pipeline-${pipeline.id}`}
                                        dataAttr={`pipeline_notification_${pipeline.id}`}
                                        label={pipeline.name}
                                        tag={PIPELINE_KIND_LABELS[pipeline.kind]}
                                        checked={isPipelineChecked(pipeline.id, enforced)}
                                        onCheckedChange={(checked) => onTogglePipeline(pipeline.id, checked)}
                                        disabledReason={lockedDisabledReason(enforced, userLoading)}
                                    />
                                ))}
                            </div>
                        </div>
                    )
                })
            )}
        </QuillNotificationSelector>
    )
}
