import { IconPerson } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonDropdown, LemonInput, Lettermark, ProfilePicture } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ErrorTrackingTeam } from 'lib/components/Errors/types'
import { fullName } from 'lib/utils'
import { useEffect, useMemo, useState } from 'react'
import { membersLogic } from 'scenes/organization/membersLogic'

import { OrganizationMemberType } from '~/types'

import { ErrorTrackingIssue } from '../../queries/schema'
import { errorTrackingTeamsLogic } from './errorTrackingTeamsLogic'

type AssigneeDisplayType = { id: number; icon: JSX.Element; displayName: string }

const unassignedUser = {
    id: 'unassigned',
    displayName: 'Unassigned',
    icon: <IconPerson className="rounded-full border border-dashed border-muted text-muted p-0.5" />,
}

export const AssigneeSelect = ({
    assignee,
    onChange,
    showName = false,
    ...buttonProps
}: {
    assignee: ErrorTrackingIssue['assignee']
    onChange: (assignee: ErrorTrackingIssue['assignee']) => void
    showName?: boolean
} & Partial<Pick<LemonButtonProps, 'type'>>): JSX.Element => {
    const { meFirstMembers, filteredMembers, search, membersLoading } = useValues(membersLogic)
    const { teams, teamsLoading } = useValues(errorTrackingTeamsLogic)
    const { ensureAllMembersLoaded, setSearch } = useActions(membersLogic)
    const { ensureAllTeamsLoaded } = useActions(errorTrackingTeamsLogic)
    const [showPopover, setShowPopover] = useState(false)

    const _onChange = (value: ErrorTrackingIssue['assignee']): void => {
        setShowPopover(false)
        onChange(value)
    }

    useEffect(() => {
        if (showPopover) {
            ensureAllMembersLoaded()
            ensureAllTeamsLoaded()
        }
    }, [showPopover, ensureAllMembersLoaded, ensureAllTeamsLoaded])

    const displayAssignee = useMemo(() => {
        if (assignee) {
            if (assignee.type === 'team') {
                const assignedTeam = teams.find((team) => team.id === assignee.id)
                return assignedTeam ? teamDisplay(assignedTeam, 0) : unassignedUser
            }

            const assignedMember = meFirstMembers.find((member) => member.user.id === assignee.id)
            return assignedMember ? userDisplay(assignedMember) : unassignedUser
        }

        return unassignedUser
    }, [assignee, meFirstMembers, teams])

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            actionable
            onVisibilityChange={(visible) => setShowPopover(visible)}
            overlay={
                <div className="max-w-100 space-y-2 overflow-hidden">
                    <LemonInput
                        type="search"
                        placeholder="Search"
                        autoFocus
                        value={search}
                        onChange={setSearch}
                        fullWidth
                    />
                    <ul className="space-y-px">
                        <li>
                            <LemonButton fullWidth role="menuitem" size="small" onClick={() => _onChange(null)}>
                                Unassign
                            </LemonButton>
                        </li>

                        <Section
                            loading={membersLoading}
                            search={!!search}
                            type="user"
                            items={filteredMembers.map(userDisplay)}
                            onSelect={_onChange}
                        />

                        <Section
                            loading={teamsLoading}
                            search={!!search}
                            type="team"
                            items={teams.map(teamDisplay)}
                            onSelect={_onChange}
                        />
                    </ul>
                </div>
            }
        >
            <LemonButton
                tooltip={displayAssignee.displayName}
                icon={displayAssignee.icon}
                sideIcon={null}
                {...buttonProps}
            >
                {showName ? <span className="pl-1">{displayAssignee.displayName}</span> : null}
            </LemonButton>
        </LemonDropdown>
    )
}

const Section = ({
    loading,
    search,
    type,
    items,
    onSelect,
}: {
    loading: boolean
    search: boolean
    type: 'user' | 'team'
    items: AssigneeDisplayType[]
    onSelect: (value: ErrorTrackingIssue['assignee']) => void
}): JSX.Element => {
    return (
        <li>
            <section className="space-y-px">
                <h5 className="mx-2 my-1">{type}s</h5>
                {items.map((item) => (
                    <li key={item.id}>
                        <LemonButton
                            fullWidth
                            role="menuitem"
                            size="small"
                            icon={item.icon}
                            onClick={() => onSelect({ type, id: item.id })}
                        >
                            <span className="flex items-center justify-between gap-2 flex-1">
                                <span>{item.displayName}</span>
                            </span>
                        </LemonButton>
                    </li>
                ))}

                {loading ? (
                    <div className="p-2 text-muted-alt italic truncate border-t">Loading...</div>
                ) : items.length === 0 ? (
                    <div className="p-2 text-muted-alt italic truncate border-t">
                        {search ? <span>No matches</span> : <span>No {type}s</span>}
                    </div>
                ) : null}
            </section>
        </li>
    )
}

const teamDisplay = (team: ErrorTrackingTeam, index: number): AssigneeDisplayType => ({
    id: team.id,
    displayName: team.name,
    icon: <Lettermark name={team.name} index={index} rounded />,
})

const userDisplay = (member: OrganizationMemberType): AssigneeDisplayType => ({
    id: member.user.id,
    displayName: fullName(member.user),
    icon: <ProfilePicture size="md" user={member.user} />,
})
