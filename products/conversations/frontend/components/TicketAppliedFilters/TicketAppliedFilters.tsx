import { LemonSnack } from '@posthog/lemon-ui'

import { AssigneeLabelDisplay, AssigneeResolver } from '../Assignee/AssigneeDisplay'
import { type AssigneeFilterEntry, toTicketAssignee } from '../Assignee/types'
import { useAppliedTicketFilters, useRemoveAppliedTicketFilter } from './appliedTicketFilters'

export function TicketAppliedFilters(): JSX.Element | null {
    const removeAppliedFilter = useRemoveAppliedTicketFilter()
    const chips = useAppliedTicketFilters()

    if (chips.length === 0) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center gap-1">
            {chips.map((chip) => (
                <LemonSnack
                    key={chip.key}
                    onClose={() => removeAppliedFilter(chip)}
                    data-attr="ticket-applied-filter"
                    title={chip.kind === 'assignee' ? undefined : chip.label}
                >
                    {chip.kind === 'assignee' ? <AssigneeFilterChipLabel entry={chip.entry} /> : chip.label}
                </LemonSnack>
            ))}
        </div>
    )
}

function AssigneeFilterChipLabel({ entry }: { entry: AssigneeFilterEntry }): JSX.Element {
    if (entry === 'me') {
        return <>Assignee: Me</>
    }
    if (entry === 'unassigned') {
        return <>Assignee: Unassigned</>
    }
    return (
        <AssigneeResolver assignee={toTicketAssignee(entry)}>
            {({ assignee }) => (
                <>
                    Assignee: <AssigneeLabelDisplay assignee={assignee} size="small" placeholder="Unknown" />
                </>
            )}
        </AssigneeResolver>
    )
}
