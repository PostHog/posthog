import { useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'

import { GroupTypeIndex } from '~/types'

import { groupKeyTooltipLogic } from './groupKeyTooltipLogic'

export interface GroupKeyFilterTooltipProps {
    groupTypeIndex: GroupTypeIndex
    groupKeys: string[]
    fallbackLabel: string
}

export function GroupKeyFilterTooltip({
    groupTypeIndex,
    groupKeys,
    fallbackLabel,
}: GroupKeyFilterTooltipProps): JSX.Element {
    const { groups, groupsLoading } = useValues(groupKeyTooltipLogic({ groupTypeIndex, groupKeys }))

    if (groupsLoading) {
        return <Spinner />
    }

    const resolved = groupKeys.map((groupKey) => groups[groupKey]).filter(Boolean)

    if (resolved.length === 0) {
        return <>{fallbackLabel}</>
    }

    return (
        <div className="flex flex-col gap-2">
            {resolved.map((group) => (
                <div key={group.group_key} className="flex flex-col">
                    <span className="font-semibold">{groupDisplayId(group.group_key, group.group_properties)}</span>
                    <span className="font-mono text-xs text-secondary">{group.group_key}</span>
                    <span className="text-xs">
                        First seen: {group.created_at ? <TZLabel time={group.created_at} /> : 'unknown'}
                    </span>
                </div>
            ))}
        </div>
    )
}
