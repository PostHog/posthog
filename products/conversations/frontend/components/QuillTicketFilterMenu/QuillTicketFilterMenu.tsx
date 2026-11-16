import { useActions, useMountedLogic, useValues } from 'kea'

import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    FilterCheckboxSubMenu,
    FilterClearItem,
    FilterMenuTrigger,
    FilterOption,
    FilterRadioSubMenu,
    FilterSearchSubMenu,
    FilterSubMenu,
} from '@posthog/quill'

import { QuillTagsFilterSubMenu } from 'lib/components/QuillTagsFilterSubMenu'
import { fullName } from 'lib/utils/strings'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import { ticketColumnChoices } from '../../scenes/tickets/ticketColumns'
import { ticketColumnsLogic } from '../../scenes/tickets/ticketColumnsLogic'
import {
    type TicketChannel,
    type TicketSlaState,
    type TicketTagsMatch,
    aiTriageFilterOptions,
    channelOptions,
    priorityMultiselectOptions,
    slaOptions,
    statusMultiselectOptions,
} from '../../types'
import { assigneeSelectLogic } from '../Assignee/assigneeSelectLogic'
import { type AssigneeFilterEntry, decodeAssigneeEntry, encodeAssigneeEntry } from '../Assignee/types'
import { useAppliedTicketFilters } from '../TicketAppliedFilters/appliedTicketFilters'

const TAGS_MATCH_OPTIONS: FilterOption<TicketTagsMatch>[] = [
    { value: 'any', label: 'Match any' },
    { value: 'all', label: 'Match all' },
]

function toFilterOptions<Value extends string>(
    options: readonly { key: Value; label: string }[]
): FilterOption<Value>[] {
    return options.map(({ key, label }) => ({ value: key, label }))
}

/**
 * The ticket list's one filter menu: the filters, then the column choice, then Clear filters. The table headers sort
 * the list, so the menu has no sort row.
 */
export function QuillTicketFilterMenu(): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const {
        statusFilter,
        priorityFilter,
        channelFilter,
        slaFilter,
        aiTriageResultFilter,
        assigneeFilterEntries,
        tagsFilter,
        tagsMatch,
        tagsExcludeFilter,
        aiEnabled,
    } = useValues(logic)
    const {
        setStatusFilter,
        setPriorityFilter,
        setChannelFilter,
        setSlaFilter,
        setAiTriageResultFilter,
        setAssigneeFilter,
        setTagsFilter,
        setTagsMatch,
        setTagsExcludeFilter,
        resetFilters,
    } = useActions(logic)
    const { me, roles, sortedMembers, membersLoading, rolesLoading } = useValues(assigneeSelectLogic)
    const { ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)
    const { visibleColumns } = useValues(ticketColumnsLogic)
    const { toggleColumn, setVisibleColumns } = useActions(ticketColumnsLogic)
    const filtersOn = useAppliedTicketFilters().length > 0

    const assigneeOptions: FilterOption[] = [
        ...(me ? [{ value: 'me', label: 'Me', hint: '(current user)' }] : []),
        { value: 'unassigned', label: 'Unassigned' },
        ...roles.map((role) => ({ value: encodeAssigneeEntry({ type: 'role', id: role.id }), label: role.name })),
        ...(sortedMembers ?? []).map((member) => ({
            value: encodeAssigneeEntry({ type: 'user', id: member.user.id }),
            label: fullName(member.user) || member.user.email,
        })),
    ]

    const { offerable, choices, shownCount, showAllDisabledReason } = ticketColumnChoices(visibleColumns, {
        aiEnabled,
        embedded: false,
    })

    return (
        <DropdownMenu
            onOpenChange={(open) => {
                // The Assignee row names the people picked, so it needs them as soon as the menu shows.
                if (open) {
                    ensureAssigneeTypesLoaded()
                }
            }}
        >
            <FilterMenuTrigger active={filtersOn} dataAttr="ticket-filters-button" />
            <DropdownMenuContent align="start" className="min-w-64">
                <FilterCheckboxSubMenu
                    label="Status"
                    allLabel="All statuses"
                    pluralNoun="statuses"
                    options={toFilterOptions(statusMultiselectOptions)}
                    selected={statusFilter}
                    onChange={setStatusFilter}
                    dataAttr="ticket-status-filter"
                />
                <FilterCheckboxSubMenu
                    label="Priority"
                    allLabel="All priorities"
                    pluralNoun="priorities"
                    options={toFilterOptions(priorityMultiselectOptions)}
                    selected={priorityFilter}
                    onChange={setPriorityFilter}
                    dataAttr="ticket-priority-filter"
                />
                <FilterRadioSubMenu<TicketChannel | 'all'>
                    label="Channel"
                    options={channelOptions}
                    value={channelFilter}
                    defaultValue="all"
                    onChange={setChannelFilter}
                    dataAttr="ticket-channel-filter"
                />
                <FilterRadioSubMenu<TicketSlaState | 'all'>
                    label="SLA"
                    options={slaOptions}
                    value={slaFilter}
                    defaultValue="all"
                    onChange={setSlaFilter}
                    dataAttr="ticket-sla-filter"
                />
                {aiEnabled && (
                    <FilterCheckboxSubMenu
                        label="AI result"
                        allLabel="Any result"
                        pluralNoun="results"
                        options={toFilterOptions(aiTriageFilterOptions)}
                        selected={aiTriageResultFilter}
                        onChange={setAiTriageResultFilter}
                        dataAttr="ticket-ai-result-filter"
                    />
                )}
                <QuillTagsFilterSubMenu
                    label="Include tags"
                    logicKey="support-tickets-include-tags"
                    selected={tagsFilter}
                    onChange={setTagsFilter}
                    dataAttr="tags-filter-input"
                    optionDataAttr="tags-filter-option"
                />
                <FilterRadioSubMenu<TicketTagsMatch>
                    label="Tag match"
                    options={TAGS_MATCH_OPTIONS}
                    value={tagsMatch}
                    defaultValue="any"
                    onChange={setTagsMatch}
                    dataAttr="tags-match-filter"
                />
                <QuillTagsFilterSubMenu
                    label="Exclude tags"
                    allLabel="No tags"
                    logicKey="support-tickets-exclude-tags"
                    selected={tagsExcludeFilter}
                    onChange={setTagsExcludeFilter}
                    dataAttr="tags-exclude-filter-input"
                    optionDataAttr="tags-exclude-filter-option"
                />
                <FilterSearchSubMenu
                    label="Assignee"
                    allLabel="All assignees"
                    pluralNoun="assignees"
                    options={assigneeOptions}
                    selected={assigneeFilterEntries.map(encodeAssigneeEntry)}
                    onChange={(tokens) =>
                        setAssigneeFilter(
                            tokens
                                .map(decodeAssigneeEntry)
                                .filter((entry): entry is AssigneeFilterEntry => entry !== null)
                        )
                    }
                    loading={membersLoading || rolesLoading}
                    searchPlaceholder="Search"
                    emptyText="No matches"
                    onOpen={ensureAssigneeTypesLoaded}
                    dataAttr="ticket-assignee-filter"
                />
                <DropdownMenuSeparator />
                <FilterSubMenu
                    label="Columns"
                    value={`${shownCount} of ${offerable.length}`}
                    dataAttr="support-tickets-column-selector"
                >
                    {choices.map((choice) => (
                        <DropdownMenuCheckboxItem
                            key={choice.key}
                            checked={choice.shown}
                            closeOnClick={false}
                            disabledReason={choice.disabledReason}
                            onCheckedChange={() => toggleColumn(choice.key)}
                        >
                            {choice.label}
                        </DropdownMenuCheckboxItem>
                    ))}
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                        closeOnClick={false}
                        disabledReason={showAllDisabledReason}
                        onClick={() => setVisibleColumns(offerable)}
                    >
                        Show all columns
                    </DropdownMenuItem>
                </FilterSubMenu>
                <FilterClearItem active={filtersOn} onClear={resetFilters} dataAttr="clear-ticket-filters" />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
