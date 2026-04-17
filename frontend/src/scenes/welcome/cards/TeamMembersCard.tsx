import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import { welcomeDialogLogic } from '../welcomeDialogLogic'

const LAST_ACTIVE_COPY: Record<string, string> = {
    today: 'Active today',
    this_week: 'Active this week',
    inactive: 'Not recently active',
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
                <LemonButton
                    type="tertiary"
                    size="small"
                    to={urls.settings('organization')}
                    onClick={() => trackCardClick('members', urls.settings('organization'))}
                >
                    See all teammates
                </LemonButton>
            </div>
            <ul className="flex flex-col gap-2">
                {teamMembers.map((member) => (
                    <li key={member.email} className="flex items-center gap-3">
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
