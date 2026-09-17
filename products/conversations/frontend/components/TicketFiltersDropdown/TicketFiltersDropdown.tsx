import { useActions, useMountedLogic, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'
import {
    LemonBadge,
    LemonButton,
    LemonCheckbox,
    LemonDropdown,
    LemonInputSelect,
    LemonLabel,
    LemonSegmentedButton,
    LemonSelect,
} from '@posthog/lemon-ui'

import { tagsModel } from '~/models/tagsModel'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
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
import { AssigneeMultiSelect } from '../Assignee/AssigneeMultiSelect'
import { useAppliedTicketFilters } from '../TicketAppliedFilters/appliedTicketFilters'

export function TicketFiltersDropdown(): JSX.Element {
    const appliedCount = useAppliedTicketFilters().length

    return (
        <LemonDropdown closeOnClickInside={false} placement="bottom-start" overlay={<TicketFiltersDropdownOverlay />}>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconFilter />}
                active={appliedCount > 0}
                data-attr="ticket-filters-button"
            >
                <span className="flex items-center gap-1">
                    Filters
                    <LemonBadge.Number count={appliedCount} size="small" maxDigits={2} />
                </span>
            </LemonButton>
        </LemonDropdown>
    )
}

function TicketFiltersDropdownOverlay(): JSX.Element {
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
    } = useActions(logic)
    const { tags: tagsAvailable } = useValues(tagsModel)
    const tagOptions = tagsAvailable?.map((t: string) => ({ key: t, label: t })) || []

    return (
        <div className="flex flex-col gap-3 p-2 w-80 max-w-full max-h-[70vh] overflow-y-auto">
            {/* max-h-[70vh]: keep every filter section reachable when the panel would overflow the window */}
            <div className="flex flex-col gap-1">
                <LemonLabel>Status</LemonLabel>
                <FilterCheckboxList
                    options={statusMultiselectOptions}
                    value={statusFilter}
                    onChange={setStatusFilter}
                />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Priority</LemonLabel>
                <FilterCheckboxList
                    options={priorityMultiselectOptions}
                    value={priorityFilter}
                    onChange={setPriorityFilter}
                />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Channel</LemonLabel>
                <LemonSelect<TicketChannel | 'all'>
                    size="small"
                    fullWidth
                    value={channelFilter}
                    onChange={(value) => setChannelFilter(value ?? 'all')}
                    options={channelOptions}
                />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>SLA</LemonLabel>
                <LemonSelect<TicketSlaState | 'all'>
                    size="small"
                    fullWidth
                    value={slaFilter}
                    onChange={(value) => setSlaFilter(value ?? 'all')}
                    options={slaOptions}
                />
            </div>
            {aiEnabled && (
                <div className="flex flex-col gap-1">
                    <LemonLabel>AI result</LemonLabel>
                    <FilterCheckboxList
                        options={aiTriageFilterOptions}
                        value={aiTriageResultFilter}
                        onChange={setAiTriageResultFilter}
                    />
                </div>
            )}
            <div className="flex flex-col gap-2">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center justify-between gap-2">
                        <LemonLabel>Include tags</LemonLabel>
                        <LemonSegmentedButton
                            size="small"
                            value={tagsMatch}
                            onChange={(value) => setTagsMatch(value as TicketTagsMatch)}
                            options={[
                                { value: 'any', label: 'Match any' },
                                { value: 'all', label: 'Match all' },
                            ]}
                        />
                    </div>
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={tagsFilter}
                        options={tagOptions}
                        onChange={setTagsFilter}
                        placeholder="Select or type tags..."
                        data-attr="tags-filter-input"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Exclude tags</LemonLabel>
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={tagsExcludeFilter}
                        options={tagOptions}
                        onChange={setTagsExcludeFilter}
                        placeholder="Exclude tags..."
                        data-attr="tags-exclude-filter-input"
                    />
                </div>
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Assignee</LemonLabel>
                <AssigneeMultiSelect value={assigneeFilterEntries} onChange={setAssigneeFilter} />
            </div>
        </div>
    )
}

function FilterCheckboxList<T extends string>({
    options,
    value,
    onChange,
}: {
    options: readonly { key: T; label: string }[]
    value: T[]
    onChange: (value: T[]) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-px">
            {options.map((option) => {
                const checked = value.includes(option.key)
                return (
                    <LemonButton
                        key={option.key}
                        type="tertiary"
                        size="small"
                        fullWidth
                        icon={<LemonCheckbox checked={checked} className="pointer-events-none" />}
                        onClick={() =>
                            onChange(checked ? value.filter((item) => item !== option.key) : [...value, option.key])
                        }
                    >
                        {option.label}
                    </LemonButton>
                )
            })}
        </div>
    )
}
