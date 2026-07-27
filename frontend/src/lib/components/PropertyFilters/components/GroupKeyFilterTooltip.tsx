import { useValues } from 'kea'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'

import { Group, GroupTypeIndex } from '~/types'

import { groupKeyTooltipLogic } from './groupKeyTooltipLogic'

export interface GroupKeyFilterTooltipProps {
    groupTypeIndex: GroupTypeIndex
    groupKey: string
    fallbackLabel: string
}

export function GroupInfoCard({ group }: { group: Group }): JSX.Element {
    return (
        <div className="flex flex-col">
            <span className="font-semibold">{groupDisplayId(group.group_key, group.group_properties)}</span>
            <CopyToClipboardInline
                selectable
                description="group key"
                tooltipMessage={null}
                className="font-mono text-xs text-secondary"
            >
                {group.group_key}
            </CopyToClipboardInline>
            <span className="text-xs">
                First seen: {group.created_at ? <TZLabel time={group.created_at} /> : 'unknown'}
            </span>
        </div>
    )
}

export function GroupKeyFilterTooltip({
    groupTypeIndex,
    groupKey,
    fallbackLabel,
}: GroupKeyFilterTooltipProps): JSX.Element {
    const { group, groupLoading } = useValues(groupKeyTooltipLogic({ groupTypeIndex, groupKey }))

    if (groupLoading) {
        return (
            <div className="flex items-center justify-center min-w-32">
                <Spinner />
            </div>
        )
    }

    if (!group) {
        return <>{fallbackLabel}</>
    }

    return <GroupInfoCard group={group} />
}
