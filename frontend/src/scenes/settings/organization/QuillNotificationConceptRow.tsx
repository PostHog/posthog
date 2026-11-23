import { useValues } from 'kea'

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger, Text } from '@posthog/quill'

import { organizationLogic } from 'scenes/organizationLogic'

import type { NotificationConcept } from '../shared/notificationSettingDescriptors'
import { listKey, notificationGovernanceLogic } from './notificationGovernanceLogic'
import { QuillNotificationMemberList } from './QuillNotificationMemberList'

function TriggerLabel({ label, count }: { label: string; count: number }): JSX.Element {
    return (
        <span className="flex flex-wrap items-center gap-2">
            <span>{label}</span>
            <Text size="xs" variant="muted" render={<span />} className="m-0">
                {count === 0 ? 'No overrides' : `${count} set`}
            </Text>
        </span>
    )
}

export function QuillNotificationConceptRow({ concept }: { concept: NotificationConcept }): JSX.Element {
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
        <Accordion>
            <AccordionItem value={concept.setting}>
                <AccordionTrigger data-attr="notification-governance-concept">
                    <TriggerLabel label={concept.label} count={count} />
                </AccordionTrigger>
                <AccordionContent className="flex flex-col gap-2">
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        {concept.description}
                    </Text>
                    {concept.perProject ? (
                        <>
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                Set per project, for named people. Someone added to a project later has no override
                                until you give them one.
                            </Text>
                            <Accordion multiple>
                                {teams.map((team) => (
                                    <AccordionItem key={team.id} value={String(team.id)}>
                                        <AccordionTrigger data-attr="notification-governance-project">
                                            <TriggerLabel
                                                label={team.name}
                                                count={ruleCountByList[listKey(concept.setting, String(team.id))] ?? 0}
                                            />
                                        </AccordionTrigger>
                                        <AccordionContent>
                                            <QuillNotificationMemberList concept={concept} scopeId={String(team.id)} />
                                        </AccordionContent>
                                    </AccordionItem>
                                ))}
                            </Accordion>
                        </>
                    ) : (
                        <QuillNotificationMemberList concept={concept} scopeId={scopeIds[0]} />
                    )}
                    {!!concept.note && (
                        <Text size="xs" variant="muted" render={<p className="m-0 italic" />}>
                            {concept.note}
                        </Text>
                    )}
                </AccordionContent>
            </AccordionItem>
        </Accordion>
    )
}
