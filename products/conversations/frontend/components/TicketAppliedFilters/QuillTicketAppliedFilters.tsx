import { useValues } from 'kea'

import { Chip, ChipClose } from '@posthog/quill'

import { fullName } from 'lib/utils/strings'

import { assigneeSelectLogic } from '../Assignee/assigneeSelectLogic'
import { type Assignee, type AssigneeFilterEntry, type TicketAssignee, toTicketAssignee } from '../Assignee/types'
import { type AppliedTicketFilter, useAppliedTicketFilters, useRemoveAppliedTicketFilter } from './appliedTicketFilters'

export function QuillTicketAppliedFilters(): JSX.Element | null {
    const removeAppliedFilter = useRemoveAppliedTicketFilter()
    const { resolveAssignee } = useValues(assigneeSelectLogic)
    const chips = useAppliedTicketFilters()

    if (chips.length === 0) {
        return null
    }

    const chipLabel = (chip: AppliedTicketFilter): string =>
        chip.kind === 'assignee' ? `Assignee: ${assigneeName(chip.entry, resolveAssignee)}` : chip.label

    return (
        <div className="flex flex-wrap items-center gap-1">
            {chips.map((chip) => {
                const label = chipLabel(chip)
                return (
                    <Chip key={chip.key} data-attr="ticket-applied-filter" title={label} className="max-w-full">
                        <span className={chip.kind === 'assignee' ? 'ph-no-capture truncate' : 'truncate'}>
                            {label}
                        </span>
                        <ChipClose aria-label={`Remove filter ${label}`} onClick={() => removeAppliedFilter(chip)} />
                    </Chip>
                )
            })}
        </div>
    )
}

function assigneeName(entry: AssigneeFilterEntry, resolveAssignee: (assignee: TicketAssignee) => Assignee): string {
    if (entry === 'me') {
        return 'Me'
    }
    if (entry === 'unassigned') {
        return 'Unassigned'
    }
    const assignee = resolveAssignee(toTicketAssignee(entry))
    if (assignee?.type === 'role') {
        return assignee.role.name
    }
    if (assignee?.type === 'user') {
        return fullName(assignee.user)
    }
    return 'Unknown'
}
