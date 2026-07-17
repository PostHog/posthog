import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    Description,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { WorkflowActivityLink } from './WorkflowActivityLink'

const nameOrLinkToTicket = (
    ticketNumber: string | undefined,
    name: string | null | undefined
): string | JSX.Element => {
    const displayName = name || `Ticket #${ticketNumber || 'unknown'}`
    return ticketNumber ? <Link to={urls.supportTicketDetail(ticketNumber)}>{displayName}</Link> : displayName
}

const formatAssignee = (
    assignee: { type?: string; user?: { email?: string }; role?: { name?: string } } | null
): string => {
    if (!assignee) {
        return 'unassigned'
    }
    if (assignee.user?.email) {
        return assignee.user.email
    }
    if (assignee.role?.name) {
        return `role: ${assignee.role.name}`
    }
    return 'unknown'
}

const ticketActionsMapping: Record<
    string,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    status: function onStatus(change) {
        return {
            description: [
                <>
                    changed status from <strong>{change?.before as string}</strong> to{' '}
                    <strong>{change?.after as string}</strong>
                </>,
            ],
        }
    },
    priority: function onPriority(change) {
        return {
            description: [
                <>
                    changed priority from <strong>{change?.before as string}</strong> to{' '}
                    <strong>{change?.after as string}</strong>
                </>,
            ],
        }
    },
    sla_due_at: function onSlaDueAt(change) {
        const before = change?.before as string | null
        const after = change?.after as string | null

        if (!before && after) {
            return {
                description: [
                    <>
                        set SLA due date to{' '}
                        <strong>
                            <TZLabel time={after} />
                        </strong>
                    </>,
                ],
            }
        }
        if (before && !after) {
            return {
                description: [<>removed SLA due date</>],
            }
        }
        return {
            description: [
                <>
                    changed SLA due date from <strong>{before ? <TZLabel time={before} /> : 'none'}</strong> to{' '}
                    <strong>{after ? <TZLabel time={after} /> : 'none'}</strong>
                </>,
            ],
        }
    },
    snoozed_until: function onSnoozedUntil(change, logItem) {
        const before = change?.before as string | null
        const after = change?.after as string | null

        if (!before && after) {
            return {
                description: [
                    <>
                        snoozed until{' '}
                        <strong>
                            <TZLabel time={after} />
                        </strong>
                    </>,
                ],
            }
        }
        if (before && !after) {
            // The same set→null change happens for a deliberate unsnooze and the system
            // wake task auto-expiring the snooze — tell them apart by actor. A workflow
            // clearing the snooze is deliberate too (it has a trigger but no user), so only
            // a change with neither a user nor a trigger is a genuine auto-expiry. Only claim
            // "reopened" when the expiry actually flipped the ticket back to open; a snooze
            // on an already-resolved ticket clears without reopening it.
            if (logItem?.user || logItem?.detail?.trigger?.job_type === 'hog_flow') {
                return { description: [<>removed snooze</>] }
            }
            const reopened = (logItem?.detail?.changes ?? []).some((c) => c.field === 'status' && c.after === 'open')
            return { description: [reopened ? <>snooze expired – reopened</> : <>snooze expired</>] }
        }
        return {
            description: [
                <>
                    changed snooze from <strong>{before ? <TZLabel time={before} /> : 'none'}</strong> to{' '}
                    <strong>{after ? <TZLabel time={after} /> : 'none'}</strong>
                </>,
            ],
        }
    },
    tag: function onTag(change) {
        const tagName = (change?.after || change?.before) as string
        if (change?.action === 'created') {
            return {
                description: [
                    <>
                        added tag <strong>{tagName}</strong>
                    </>,
                ],
            }
        }
        if (change?.action === 'deleted') {
            return {
                description: [
                    <>
                        removed tag <strong>{tagName}</strong>
                    </>,
                ],
            }
        }
        return null
    },
}

export function ticketActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== 'Ticket') {
        console.error('ticket describer received a non-ticket activity')
        return { description: null }
    }

    // When a HogFlow workflow step made the change, attribute it to (and link to) the workflow
    // instead of the generic "PostHog" system actor. The workflow name is resolved live by id
    // (never trusted from the log payload), so it can't be spoofed via the update headers.
    const trigger = logItem.detail.trigger
    const actor =
        trigger?.job_type === 'hog_flow' && trigger.job_id ? (
            <WorkflowActivityLink id={trigger.job_id} />
        ) : (
            <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>
        )
    const ticketNumber = logItem.detail.name?.replace(/^Ticket #/, '')
    const ticketLink = nameOrLinkToTicket(ticketNumber, logItem.detail.name)

    if (logItem.activity === 'created') {
        return {
            description: (
                <>
                    {actor} created {ticketLink}
                </>
            ),
        }
    }

    if (logItem.activity === 'assigned') {
        const changes = logItem.detail.changes || []
        const assigneeChange = changes.find((c) => c.field === 'assignee')
        const after = (assigneeChange?.after ?? null) as {
            type?: string
            user?: { email?: string }
            role?: { name?: string }
        } | null
        return {
            description: (
                <>
                    {actor} assigned {ticketLink} to <strong>{formatAssignee(after)}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        const allChanges: Description[] = []

        for (const change of logItem.detail.changes || []) {
            if (!change?.field) {
                continue
            }

            const handler = ticketActionsMapping[change.field]
            const result = handler?.(change, logItem)
            if (result?.description) {
                allChanges.push(...result.description)
            }
        }

        if (allChanges.length === 1) {
            return {
                description: (
                    <>
                        {actor} {allChanges[0]} on {ticketLink}
                    </>
                ),
            }
        }

        if (allChanges.length > 1) {
            return {
                description: (
                    <>
                        {actor} made changes to {ticketLink}:
                        <ul className="bullet-list">
                            {allChanges.map((desc, i) => (
                                <li key={i}>{desc}</li>
                            ))}
                        </ul>
                    </>
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification, ticketLink)
}
