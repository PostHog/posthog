import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import { welcomeDialogLogic } from '../welcomeDialogLogic'

const LAST_ACTIVE_SUFFIX: Record<string, string> = {
    today: ' — active today',
    this_week: ' — active this week',
    inactive: ' — inactive',
    never: " — hasn't signed in",
}

export function TeamMembersCard(): JSX.Element | null {
    const { teamMembers } = useValues(welcomeDialogLogic)
    const { trackCardClick } = useActions(welcomeDialogLogic)

    if (teamMembers.length === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="p-4">
            <div className="flex items-center gap-3">
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold">Your team</div>
                    <div className="text-xs text-muted">
                        {teamMembers.length} {teamMembers.length === 1 ? 'teammate' : 'teammates'}
                    </div>
                </div>
                <ProfileBubbles
                    people={teamMembers.map((member) => ({
                        email: member.email,
                        name: member.name,
                        title: `${member.name}${LAST_ACTIVE_SUFFIX[member.last_active] ?? ''}`,
                    }))}
                    limit={6}
                />
                <Link
                    to={urls.settings('organization')}
                    subtle
                    onClick={() => trackCardClick('members', urls.settings('organization'))}
                    className="inline-flex items-center gap-1 text-xs text-muted flex-shrink-0"
                >
                    <span>See all</span>
                    <IconArrowRight />
                </Link>
            </div>
        </LemonCard>
    )
}
