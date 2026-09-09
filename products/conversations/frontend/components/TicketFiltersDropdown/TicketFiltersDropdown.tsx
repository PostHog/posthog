import { useActions, useMountedLogic, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import {
    Badge,
    Button,
    ItemCheckbox,
    ItemContent,
    ItemTitle,
    Label,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    ToggleGroup,
    ToggleGroupItem,
} from 'lib/ui/quill'

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
        <Popover>
            <PopoverTrigger render={<Button variant="outline" size="sm" data-attr="ticket-filters-button" />}>
                <IconFilter />
                Filters
                {appliedCount > 0 ? <Badge>{appliedCount}</Badge> : null}
            </PopoverTrigger>
            <PopoverContent align="start" className="w-80 max-w-full p-2">
                <TicketFiltersDropdownOverlay />
            </PopoverContent>
        </Popover>
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

    return (
        <div className="flex flex-col gap-3 max-h-[70vh] overflow-y-auto">
            {/* max-h-[70vh]: keep every filter section reachable when the panel would overflow the window */}
            <div className="flex flex-col gap-1">
                <Label>Status</Label>
                <FilterCheckboxList
                    options={statusMultiselectOptions}
                    value={statusFilter}
                    onChange={setStatusFilter}
                />
            </div>
            <div className="flex flex-col gap-1">
                <Label>Priority</Label>
                <FilterCheckboxList
                    options={priorityMultiselectOptions}
                    value={priorityFilter}
                    onChange={setPriorityFilter}
                />
            </div>
            <div className="flex flex-col gap-1">
                <Label>Channel</Label>
                <Select
                    value={channelFilter}
                    onValueChange={(value: TicketChannel | 'all' | null) => {
                        if (value) {
                            setChannelFilter(value)
                        }
                    }}
                >
                    <SelectTrigger size="sm" className="w-full">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent align="start" alignItemWithTrigger={false}>
                        {channelOptions.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </div>
            <div className="flex flex-col gap-1">
                <Label>SLA</Label>
                <Select
                    value={slaFilter}
                    onValueChange={(value: TicketSlaState | 'all' | null) => {
                        if (value) {
                            setSlaFilter(value)
                        }
                    }}
                >
                    <SelectTrigger size="sm" className="w-full">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent align="start" alignItemWithTrigger={false}>
                        {slaOptions.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </div>
            {aiEnabled && (
                <div className="flex flex-col gap-1">
                    <Label>AI result</Label>
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
                        <Label>Include tags</Label>
                        <ToggleGroup
                            variant="outline"
                            size="sm"
                            value={[tagsMatch]}
                            onValueChange={([value]) => {
                                if (value === 'any' || value === 'all') {
                                    setTagsMatch(value as TicketTagsMatch)
                                }
                            }}
                        >
                            <ToggleGroupItem value="any">Match any</ToggleGroupItem>
                            <ToggleGroupItem value="all">Match all</ToggleGroupItem>
                        </ToggleGroup>
                    </div>
                    <TagsCombobox
                        value={tagsFilter}
                        onChange={setTagsFilter}
                        options={tagsAvailable ?? []}
                        placeholder="Select or type tags..."
                        dataAttr="tags-filter-input"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <Label>Exclude tags</Label>
                    <TagsCombobox
                        value={tagsExcludeFilter}
                        onChange={setTagsExcludeFilter}
                        options={tagsAvailable ?? []}
                        placeholder="Exclude tags..."
                        dataAttr="tags-exclude-filter-input"
                    />
                </div>
            </div>
            <div className="flex flex-col gap-1">
                <Label>Assignee</Label>
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
                    <ItemCheckbox
                        key={option.key}
                        size="xs"
                        aria-checked={checked}
                        onClick={() =>
                            onChange(checked ? value.filter((item) => item !== option.key) : [...value, option.key])
                        }
                    >
                        <ItemContent variant="menuItem">
                            <ItemTitle>{option.label}</ItemTitle>
                        </ItemContent>
                    </ItemCheckbox>
                )
            })}
        </div>
    )
}
