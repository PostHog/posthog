import { AvatarGroup, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { WelcomeLastActive, WelcomeTeamMember } from 'scenes/welcome/welcomeDialogLogic'

import { TaskUserAvatar } from 'products/tasks/frontend/spaces/TaskUserAvatar'

const MAX_AVATARS = 8

const LAST_ACTIVE: Record<WelcomeLastActive, string> = {
    today: 'active today',
    this_week: 'active this week',
    inactive: 'not active lately',
    never: 'has not signed in yet',
}

export function WaysToUseTeammates({ members }: { members: WelcomeTeamMember[] }): JSX.Element {
    const shown = members.slice(0, MAX_AVATARS)

    return (
        <AvatarGroup stacked reverse size="xs" data-attr="today-ways-to-use-teammates">
            {[...shown].reverse().map((member) => {
                const name = member.name || member.email
                const label = `${name}, ${LAST_ACTIVE[member.last_active]}`
                return (
                    <Tooltip key={member.email}>
                        <TooltipTrigger
                            render={<span role="img" aria-label={label} className="relative flex shrink-0" />}
                        >
                            <TaskUserAvatar user={{ first_name: name, last_name: '', email: member.email }} />
                            {member.last_active === 'today' && (
                                <span className="absolute right-0 bottom-0 size-1.5 rounded-full bg-primary ring-1 ring-background" />
                            )}
                        </TooltipTrigger>
                        <TooltipContent>{label}</TooltipContent>
                    </Tooltip>
                )
            })}
        </AvatarGroup>
    )
}
