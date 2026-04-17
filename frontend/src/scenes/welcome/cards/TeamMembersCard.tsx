import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import { welcomeDialogLogic } from '../welcomeDialogLogic'

const LAST_ACTIVE_COPY: Record<string, string> = {
    today: 'Active today',
    this_week: 'Active this week',
    inactive: 'Inactive',
    never: "Hasn't signed in",
}

export function TeamMembersCard(): JSX.Element | null {
    const { teamMembers } = useValues(welcomeDialogLogic)
    const { trackCardClick } = useActions(welcomeDialogLogic)

    if (teamMembers.length === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="p-6">
            <div className="flex items-center justify-between mb-3">
                <h2 className="text-lg font-semibold">Your team</h2>
                <Link
                    to={urls.settings('organization')}
                    subtle
                    onClick={() => trackCardClick('members', urls.settings('organization'))}
                    className="inline-flex items-center gap-1 text-xs text-muted"
                >
                    <span>See all members</span>
                    <IconArrowRight />
                </Link>
            </div>
            <ul className="flex flex-col gap-2">
                {teamMembers.map((member) => (
                    <li
                        key={member.email}
                        className="flex items-center gap-3"
                        title={`${member.name} <${member.email}>`}
                    >
                        <ProfilePicture user={{ first_name: member.name, email: member.email }} size="md" />
                        <div className="flex-1 min-w-0">
                            <div className="truncate font-medium">{member.name}</div>
                            <div className="text-xs text-muted capitalize">{member.role}</div>
                        </div>
                        <div className="text-xs text-muted whitespace-nowrap">
                            {LAST_ACTIVE_COPY[member.last_active] ?? member.last_active}
                        </div>
                    </li>
                ))}
            </ul>
        </LemonCard>
    )
}
