import { useActions, useValues } from 'kea'

import { Button, Collapsible, CollapsibleContent, CollapsibleHeader, CollapsibleTrigger, Text } from '@posthog/quill'

import { REALTIME_NOTIFICATION_TYPE_META } from 'lib/components/NotificationsMenu/NotificationRow'
import { userLogic } from 'scenes/userLogic'

import { TeamBasicType } from '~/types'

import { QuillNotificationCheckbox } from './QuillNotificationCheckbox'
import { ProjectState, realtimeNotificationPreferencesLogic } from './realtimeNotificationPreferencesLogic'

export function QuillRealtimeNotificationPreferences({
    onSetAll,
    onToggleProject,
}: {
    onSetAll: (enabled: boolean) => void
    onToggleProject: (teamId: number, state: ProjectState) => void
}): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { updateRealtimeNotificationForTeam } = useActions(userLogic)
    const { activeTypes, isTypeEnabledForTeam, projectState, teams, isProjectExpanded, allOn, allOff } = useValues(
        realtimeNotificationPreferencesLogic
    )
    const { setProjectExpanded } = useActions(realtimeNotificationPreferencesLogic)

    if (activeTypes.length === 0) {
        return (
            <Text size="xs" variant="muted" className="m-0">
                No real-time notifications are wired up for your account yet.
            </Text>
        )
    }

    const loadingReason = userLoading ? 'Loading...' : undefined

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <Button
                    variant="outline"
                    disabledReason={loadingReason ?? (allOn ? 'All notifications are already on' : undefined)}
                    onClick={() => onSetAll(true)}
                >
                    Enable all
                </Button>
                <Button
                    variant="outline"
                    disabledReason={loadingReason ?? (allOff ? 'All notifications are already off' : undefined)}
                    onClick={() => onSetAll(false)}
                >
                    Disable all
                </Button>
            </div>

            <div className="flex flex-col gap-2">
                {teams.map((team: TeamBasicType) => {
                    const state = projectState(team.id)

                    return (
                        <Collapsible
                            key={team.id}
                            variant="folder"
                            open={isProjectExpanded(team.id)}
                            onOpenChange={(open) => setProjectExpanded(team.id, open)}
                        >
                            <CollapsibleHeader>
                                <CollapsibleTrigger
                                    iconOnly
                                >{`Notification types for ${team.name}`}</CollapsibleTrigger>
                                <QuillNotificationCheckbox
                                    id={`realtime-project-${team.id}`}
                                    label={team.name}
                                    tag={`id: ${team.id}`}
                                    checked={state === 'on'}
                                    indeterminate={state === 'partial'}
                                    disabledReason={loadingReason}
                                    onCheckedChange={() => onToggleProject(team.id, state)}
                                />
                            </CollapsibleHeader>
                            <CollapsibleContent className="flex flex-col gap-2 ps-14">
                                {activeTypes.map((type) => {
                                    const meta = REALTIME_NOTIFICATION_TYPE_META[type] ?? {
                                        label: type,
                                        description: '',
                                    }

                                    return (
                                        <QuillNotificationCheckbox
                                            key={`${team.id}-${type}`}
                                            id={`realtime-${type}-${team.id}`}
                                            label={meta.label}
                                            description={meta.description || undefined}
                                            checked={isTypeEnabledForTeam(type, team.id)}
                                            disabledReason={loadingReason}
                                            onCheckedChange={(checked) =>
                                                updateRealtimeNotificationForTeam(type, team.id, checked)
                                            }
                                        />
                                    )
                                })}
                            </CollapsibleContent>
                        </Collapsible>
                    )
                })}
            </div>
        </div>
    )
}
