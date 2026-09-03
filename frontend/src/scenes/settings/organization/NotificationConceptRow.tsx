import { useValues } from 'kea'

import { LemonCollapse } from '@posthog/lemon-ui'

import { organizationLogic } from 'scenes/organizationLogic'

import type { NotificationConcept } from '../shared/notificationSettingDescriptors'
import { listKey, notificationGovernanceLogic } from './notificationGovernanceLogic'
import { NotificationMemberList } from './NotificationMemberList'

function CollapseHeader({ label, count }: { label: string; count: number }): JSX.Element {
    return (
        <span className="flex-1 flex items-center justify-between gap-2">
            <span>{label}</span>
            <span className="text-muted text-xs">{count === 0 ? 'No overrides' : `${count} set`}</span>
        </span>
    )
}

export function NotificationConceptRow({ concept }: { concept: NotificationConcept }): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { ruleCountByList } = useValues(notificationGovernanceLogic)

    const teams = currentOrganization?.teams ?? []
    const scopeIds = concept.perProject
        ? teams.map((team) => String(team.id))
        : [concept.setting === 'organization_member_join_email_disabled' ? (currentOrganization?.id ?? '') : '']
    const count = scopeIds.reduce(
        (total, scopeId) => total + (ruleCountByList[listKey(concept.setting, scopeId)] ?? 0),
        0
    )

    return (
        <LemonCollapse
            panels={[
                {
                    key: concept.setting,
                    dataAttr: 'notification-governance-concept',
                    header: <CollapseHeader label={concept.label} count={count} />,
                    content: (
                        <div className="deprecated-space-y-2">
                            <p className="text-muted text-xs mb-0">{concept.description}</p>
                            {concept.perProject ? (
                                <>
                                    <p className="text-muted text-xs mb-0">
                                        Set per project, for named people. Someone added to a project later has no
                                        override until you give them one.
                                    </p>
                                    <LemonCollapse
                                        multiple
                                        embedded
                                        panels={teams.map((team) => ({
                                            key: String(team.id),
                                            dataAttr: 'notification-governance-project',
                                            header: (
                                                <CollapseHeader
                                                    label={team.name}
                                                    count={
                                                        ruleCountByList[listKey(concept.setting, String(team.id))] ?? 0
                                                    }
                                                />
                                            ),
                                            content: (
                                                <NotificationMemberList concept={concept} scopeId={String(team.id)} />
                                            ),
                                        }))}
                                    />
                                </>
                            ) : (
                                <NotificationMemberList concept={concept} scopeId={scopeIds[0]} />
                            )}
                            {!!concept.note && <p className="text-muted text-xs italic mb-0">{concept.note}</p>}
                        </div>
                    ),
                },
            ]}
        />
    )
}
