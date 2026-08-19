import { useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { organizationLogic } from 'scenes/organizationLogic'

import type { OrganizationNotificationMemberApi } from '~/generated/core/api.schemas'

import type { NotificationConcept } from '../shared/notificationSettingDescriptors'
import { listKey, notificationGovernanceLogic } from './notificationGovernanceLogic'
import { NotificationMemberList } from './NotificationMemberList'

function RuleCount({ count }: { count: number }): JSX.Element {
    return <span className="text-muted text-xs">{count === 0 ? 'No overrides' : `${count} set`}</span>
}

function ProjectRow({
    concept,
    teamId,
    teamName,
    members,
}: {
    concept: NotificationConcept
    teamId: string
    teamName: string
    members: OrganizationNotificationMemberApi[]
}): JSX.Element {
    const { ruleCountByList } = useValues(notificationGovernanceLogic)
    const [expanded, setExpanded] = useState(false)

    return (
        <div className="border rounded p-3 deprecated-space-y-2 bg-surface-secondary">
            <div className="flex items-center justify-between gap-2">
                <LemonButton
                    icon={expanded ? <IconChevronDown /> : <IconChevronRight />}
                    onClick={() => setExpanded(!expanded)}
                    size="small"
                    type="tertiary"
                    className="p-0"
                    data-attr="notification-governance-project"
                >
                    {teamName}
                </LemonButton>
                <RuleCount count={ruleCountByList[listKey(concept.setting, teamId)] ?? 0} />
            </div>
            {expanded && <NotificationMemberList concept={concept} scopeId={teamId} members={members} />}
        </div>
    )
}

export function NotificationConceptRow({ concept }: { concept: NotificationConcept }): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { members, ruleCountByList } = useValues(notificationGovernanceLogic)
    const [expanded, setExpanded] = useState(false)

    const teams = currentOrganization?.teams ?? []
    const scopeIds = concept.perProject
        ? teams.map((team) => String(team.id))
        : [concept.setting === 'organization_member_join_email_disabled' ? (currentOrganization?.id ?? '') : '']
    const count = scopeIds.reduce(
        (total, scopeId) => total + (ruleCountByList[listKey(concept.setting, scopeId)] ?? 0),
        0
    )
    const listed = members ?? []

    return (
        <div className="border rounded p-3 deprecated-space-y-2">
            <div className="flex items-center justify-between gap-2">
                <LemonButton
                    icon={expanded ? <IconChevronDown /> : <IconChevronRight />}
                    onClick={() => setExpanded(!expanded)}
                    size="small"
                    type="tertiary"
                    className="p-0"
                    data-attr="notification-governance-concept"
                >
                    {concept.label}
                </LemonButton>
                <RuleCount count={count} />
            </div>
            <p className="text-muted text-xs mb-0">{concept.description}</p>

            {expanded && (
                <div className="ml-6 deprecated-space-y-2">
                    {concept.perProject ? (
                        <>
                            <p className="text-muted text-xs mb-0">
                                Set per project, for named people. Someone added to a project later has no override
                                until you give them one.
                            </p>
                            {teams.map((team) => (
                                <ProjectRow
                                    key={team.id}
                                    concept={concept}
                                    teamId={String(team.id)}
                                    teamName={team.name}
                                    members={listed}
                                />
                            ))}
                        </>
                    ) : (
                        <NotificationMemberList concept={concept} scopeId={scopeIds[0]} members={listed} />
                    )}
                    {!!concept.note && <p className="text-muted text-xs italic mb-0">{concept.note}</p>}
                </div>
            )}
        </div>
    )
}
