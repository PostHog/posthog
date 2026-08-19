import type { ReactNode } from 'react'

import { type TicketViewFilters, normalizeAssigneeFilter } from '../../types'
import { AssigneeLabelDisplay, AssigneeResolver } from '../Assignee'

export function FiltersSummary({ filters }: { filters: TicketViewFilters }): JSX.Element {
    const lines: { label: string; value: ReactNode }[] = []

    if (filters.status?.length) {
        lines.push({ label: 'Status', value: filters.status.join(', ') })
    }
    if (filters.priority?.length) {
        lines.push({ label: 'Priority', value: filters.priority.join(', ') })
    }
    if (filters.channel && filters.channel !== 'all') {
        lines.push({ label: 'Channel', value: filters.channel })
    }
    if (filters.sla && filters.sla !== 'all') {
        lines.push({ label: 'SLA', value: filters.sla })
    }
    if (filters.tags?.length) {
        lines.push({
            label: filters.tagsMatch === 'all' ? 'Tags (all)' : 'Tags (any)',
            value: filters.tags.join(', '),
        })
    }
    if (filters.tagsExclude?.length) {
        lines.push({ label: 'Exclude tags', value: filters.tagsExclude.join(', ') })
    }
    const assigneeEntries = normalizeAssigneeFilter(filters.assignee)
    if (assigneeEntries.length) {
        lines.push({
            label: 'Assignee',
            value: assigneeEntries.map((entry, index) => (
                <span key={typeof entry === 'string' ? entry : `${entry.type}:${entry.id}`}>
                    {index > 0 ? ', ' : ''}
                    {entry === 'unassigned' ? (
                        'Unassigned'
                    ) : entry === 'me' ? (
                        'Me (current user)'
                    ) : (
                        <AssigneeResolver assignee={entry}>
                            {({ assignee }) => (
                                <AssigneeLabelDisplay assignee={assignee} placeholder={`${entry.type}:${entry.id}`} />
                            )}
                        </AssigneeResolver>
                    )}
                </span>
            )),
        })
    }
    if (filters.dateFrom) {
        lines.push({ label: 'Date from', value: filters.dateFrom })
    }

    if (lines.length === 0) {
        return <span className="text-muted text-xs">No filters</span>
    }
    return (
        <div className="text-xs text-muted space-y-0.5">
            {lines.map((line) => (
                <div key={line.label}>
                    <span className="font-medium">{line.label}:</span> {line.value}
                </div>
            ))}
        </div>
    )
}
