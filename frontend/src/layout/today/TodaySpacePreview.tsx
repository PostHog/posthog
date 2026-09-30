import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconLock } from '@posthog/icons'
import { Skeleton } from '@posthog/quill'

import { fullNameOrEmail } from 'lib/utils/strings'

import { ChannelDTOApi, TaskUserBasicInfoApi } from 'products/tasks/frontend/generated/api.schemas'

import { todayPreviewCardLogic } from './todayPreviewCardLogic'
import { TodayPreviewFacts } from './TodayPreviewFacts'
import { isLockedSpace, spaceLabel } from './todaySpacesLogic'

const MAX_PEOPLE = 3
const MAX_REPOSITORIES = 3

function spaceKind(space: ChannelDTOApi): string {
    if (space.system_role === 'personal' || space.channel_type === 'personal') {
        return 'Personal space'
    }
    return space.channel_type === 'private' ? 'Private space' : 'Space'
}

function listNames(names: string[], max: number): string {
    const shown = names.slice(0, max).join(', ')
    return names.length > max ? `${shown} and ${names.length - max} more` : shown
}

/** Who can see the space. `undefined` while a private space's members load. */
function spacePeople(
    space: ChannelDTOApi,
    members: TaskUserBasicInfoApi[] | null | undefined
): string | null | undefined {
    if (space.system_role === 'personal' || space.channel_type === 'personal') {
        return 'Only you'
    }
    if (space.channel_type !== 'private') {
        return 'Everyone in this project'
    }
    if (members === undefined) {
        return undefined
    }
    return members?.length ? listNames(members.map(fullNameOrEmail), MAX_PEOPLE) : null
}

export function TodaySpacePreview({ space }: { space: ChannelDTOApi }): JSX.Element {
    const { spaceMembers } = useValues(todayPreviewCardLogic)
    const { previewOpened } = useActions(todayPreviewCardLogic)

    useEffect(() => {
        previewOpened({ kind: 'space', space })
        // The card keys this component on the row, so this counts one open for each row.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const people = spacePeople(space, spaceMembers[space.id])
    const repositories = space.repositories.length ? listNames(space.repositories, MAX_REPOSITORIES) : null
    return (
        <>
            <div className="flex min-w-0 items-center gap-2">
                <span className="flex size-3.5 shrink-0 items-center justify-center text-muted-foreground">
                    {isLockedSpace(space) ? <IconLock /> : <span className="font-mono">#</span>}
                </span>
                <span className="min-w-0 font-semibold text-foreground wrap-anywhere">{spaceLabel(space)}</span>
            </div>
            <div className="text-xs text-muted-foreground">{spaceKind(space)}</div>
            {people === undefined ? (
                <Skeleton className="h-3 w-40" />
            ) : (
                <TodayPreviewFacts
                    facts={[
                        { label: 'People', value: people },
                        { label: 'Repositories', value: repositories },
                        {
                            label: 'Created by',
                            value: space.created_by && !space.system_role ? fullNameOrEmail(space.created_by) : null,
                        },
                    ]}
                />
            )}
        </>
    )
}
