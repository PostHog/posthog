import { TeamBasicType } from '~/types'

import { lockedDisabledReason } from '../shared/notificationLocks'
import { QuillNotificationCheckbox } from './QuillNotificationCheckbox'
import { QuillNotificationSelector } from './QuillNotificationSelector'

export function QuillProjectDigestSelector({
    teams,
    keyPrefix,
    dataAttrPrefix,
    expanded,
    onExpandedChange,
    hint,
    enforcedFor,
    isTeamChecked,
    userLoading,
    onToggleTeam,
    onEnableAll,
    onDisableAll,
    bulkDisabledReason,
}: {
    teams: TeamBasicType[]
    keyPrefix: string
    dataAttrPrefix: string
    expanded: boolean
    onExpandedChange: (expanded: boolean) => void
    hint?: string
    enforcedFor: (teamId: number) => boolean | null
    isTeamChecked: (teamId: number, enforced: boolean | null) => boolean
    userLoading: boolean
    onToggleTeam: (teamId: number, enabled: boolean) => void
    onEnableAll: () => void
    onDisableAll: () => void
    bulkDisabledReason?: string
}): JSX.Element {
    return (
        <QuillNotificationSelector
            title={`Select projects (${teams.length} available)`}
            expanded={expanded}
            onExpandedChange={onExpandedChange}
            className="ps-9"
            hint={hint}
            bulkActions={{
                enableLabel: 'Enable for all projects',
                disableLabel: 'Disable for all projects',
                onEnableAll,
                onDisableAll,
                disabledReason: bulkDisabledReason,
            }}
        >
            {teams.map((team) => {
                const enforced = enforcedFor(team.id)

                return (
                    <QuillNotificationCheckbox
                        key={`${keyPrefix}-${team.id}`}
                        id={`${keyPrefix}-${team.id}`}
                        dataAttr={`${dataAttrPrefix}_${team.id}`}
                        label={team.name}
                        tag={`id: ${team.id}`}
                        lockedByAdmin={enforced !== null}
                        checked={isTeamChecked(team.id, enforced)}
                        onCheckedChange={(checked) => onToggleTeam(team.id, checked)}
                        disabledReason={lockedDisabledReason(enforced, userLoading)}
                    />
                )
            })}
        </QuillNotificationSelector>
    )
}
