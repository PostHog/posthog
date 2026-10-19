import { Avatar, AvatarFallback, AvatarGroup, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { WelcomeLastActive, WelcomeTeamMember } from 'scenes/welcome/welcomeDialogLogic'

import { TaskUserAvatar } from 'products/tasks/frontend/spaces/TaskUserAvatar'

const MAX_AVATARS = 7

const LAST_ACTIVE: Record<WelcomeLastActive, string> = {
    today: 'active today',
    this_week: 'active this week',
    inactive: 'not active lately',
    never: 'has not signed in yet',
}

const ACTIVITY_ORDER: WelcomeLastActive[] = ['today', 'this_week', 'inactive', 'never']

export function WaysToUseTeammates({ members }: { members: WelcomeTeamMember[] }): JSX.Element {
    const sorted = [...members].sort(
        (a, b) => ACTIVITY_ORDER.indexOf(a.last_active) - ACTIVITY_ORDER.indexOf(b.last_active)
    )
    const shown = sorted.slice(0, MAX_AVATARS)
    const hidden = sorted.length - shown.length

    return (
        <AvatarGroup stacked size="xs" className="[--avatar-overlap:0.375rem]" data-attr="today-ways-to-use-teammates">
            {shown.map((member) => {
                const name = member.name || member.email
                const label = `${name}, ${LAST_ACTIVE[member.last_active]}`
                return (
                    <Tooltip key={member.email}>
                        <TooltipTrigger
                            render={<span role="img" aria-label={label} className="relative flex shrink-0" />}
                        >
                            <TaskUserAvatar
                                user={{ first_name: name, last_name: '', email: member.email }}
                                className="[--avatar-size:1.75rem] text-xs"
                            />
                        </TooltipTrigger>
                        <TooltipContent>{label}</TooltipContent>
                    </Tooltip>
                )
            })}
            {hidden > 0 && (
                <Avatar size="xs" className="[--avatar-size:1.75rem] text-xs">
                    <AvatarFallback>{`+${hidden}`}</AvatarFallback>
                </Avatar>
            )}
        </AvatarGroup>
    )
}
