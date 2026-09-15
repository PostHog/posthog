import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonSnack } from '@posthog/lemon-ui'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import { AssigneeLabelDisplay, AssigneeResolver } from '../Assignee/AssigneeDisplay'
import { type AssigneeFilterEntry, isSameAssigneeEntry, toTicketAssignee } from '../Assignee/types'
import { type AppliedTicketFilter, useAppliedTicketFilters } from './appliedTicketFilters'

export function TicketAppliedFilters(): JSX.Element | null {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const { statusFilter, priorityFilter, aiTriageResultFilter, assigneeFilterEntries, tagsFilter, tagsExcludeFilter } =
        useValues(logic)
    const {
        setStatusFilter,
        setPriorityFilter,
        setChannelFilter,
        setSlaFilter,
        setAiTriageResultFilter,
        setAssigneeFilter,
        setTagsFilter,
        setTagsExcludeFilter,
        resetFilters,
    } = useActions(logic)

    const chips = useAppliedTicketFilters()

    if (chips.length === 0) {
        return null
    }

    const onRemove = (chip: AppliedTicketFilter): void => {
        switch (chip.kind) {
            case 'status':
                setStatusFilter(statusFilter.filter((status) => status !== chip.value))
                break
            case 'priority':
                setPriorityFilter(priorityFilter.filter((priority) => priority !== chip.value))
                break
            case 'channel':
                setChannelFilter('all')
                break
            case 'sla':
                setSlaFilter('all')
                break
            case 'ai':
                setAiTriageResultFilter(aiTriageResultFilter.filter((result) => result !== chip.value))
                break
            case 'tag':
                setTagsFilter(tagsFilter.filter((tag) => tag !== chip.value))
                break
            case 'tag-exclude':
                setTagsExcludeFilter(tagsExcludeFilter.filter((tag) => tag !== chip.value))
                break
            case 'assignee':
                setAssigneeFilter(assigneeFilterEntries.filter((entry) => !isSameAssigneeEntry(entry, chip.entry)))
                break
        }
    }

    return (
        <div className="flex flex-wrap items-center gap-1">
            {chips.map((chip) => (
                <LemonSnack
                    key={chip.key}
                    onClose={() => onRemove(chip)}
                    data-attr="ticket-applied-filter"
                    title={chip.kind === 'assignee' ? undefined : chip.label}
                >
                    {chip.kind === 'assignee' ? <AssigneeFilterChipLabel entry={chip.entry} /> : chip.label}
                </LemonSnack>
            ))}
            <LemonButton type="tertiary" size="small" onClick={resetFilters} data-attr="clear-ticket-filters">
                Clear all filters
            </LemonButton>
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
