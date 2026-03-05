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
    assignee: function onAssignee(change) {
        const before = change?.before as { type?: string; user?: { email?: string }; role?: { name?: string } } | null
        const after = change?.after as { type?: string; user?: { email?: string }; role?: { name?: string } } | null
        return {
            description: [
                <>
                    changed assignee from <strong>{formatAssignee(before)}</strong> to{' '}
                    <strong>{formatAssignee(after)}</strong>
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
    tags: function onTags(change) {
        const before = (change?.before as string[]) || []
        const after = (change?.after as string[]) || []
        const added = after.filter((t) => !before.includes(t))
        const removed = before.filter((t) => !after.includes(t))

        const changes: Description[] = []
        if (added.length) {
            changes.push(
                <>
                    added tag{added.length > 1 ? 's' : ''} <strong>{added.join(', ')}</strong>
                </>
            )
        }
        if (removed.length) {
            changes.push(
                <>
                    removed tag{removed.length > 1 ? 's' : ''} <strong>{removed.join(', ')}</strong>
                </>
            )
        }

        return changes.length > 0 ? { description: changes } : null
    },
}

export function ticketActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== 'Ticket') {
        console.error('ticket describer received a non-ticket activity')
        return { description: null }
    }

    const user = <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>
    const ticketNumber = logItem.detail.name?.replace(/^Ticket #/, '')
    const ticketLink = nameOrLinkToTicket(ticketNumber, logItem.detail.name)

    if (logItem.activity === 'created') {
        return {
            description: (
                <>
                    {user} created {ticketLink}
                </>
            ),
        }
    }

    if (logItem.activity === 'assigned') {
        const changes = logItem.detail.changes || []
        const assigneeChange = changes.find((c) => c.field === 'assignee')
        if (assigneeChange) {
            const after = assigneeChange.after as {
                type?: string
                user?: { email?: string }
                role?: { name?: string }
            } | null
            return {
                description: (
                    <>
                        {user} assigned {ticketLink} to <strong>{formatAssignee(after)}</strong>
                    </>
                ),
            }
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
                        {user} {allChanges[0]} on {ticketLink}
                    </>
                ),
            }
        }

        if (allChanges.length > 1) {
            return {
                description: (
                    <>
                        {user} made changes to {ticketLink}:
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
