import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonCheckbox, LemonDropdown, LemonInputSelect, LemonSegmentedButton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { tagsModel } from '~/models/tagsModel'

import { clearFilterButtonProps } from '../../clearFilterButtonProps'
import { AssigneeMultiSelect } from '../../components/Assignee'
import {
    type AITriageFilterValue,
    type TicketSlaState,
    type TicketTagsMatch,
    aiTriageFilterOptions,
    channelOptions,
    priorityMultiselectOptions,
    slaOptions,
    statusMultiselectOptions,
} from '../../types'
import { supportTicketsSceneLogic } from './supportTicketsSceneLogic'
import { TICKET_FILTER_LABELS, type TicketFilterKey, ticketFilterBarLogic } from './ticketFilterBarLogic'

interface TicketFilterChipProps {
    filterKey: TicketFilterKey
    /** Open the dropdown as soon as the chip appears, so adding a filter and picking a value is one step. */
    autoOpen?: boolean
}

interface MultiSelectOverlayProps<T extends string> {
    options: { key: T; label: string }[]
    selected: T[]
    onChange: (selected: T[]) => void
}

function MultiSelectOverlay<T extends string>({
    options,
    selected,
    onChange,
}: MultiSelectOverlayProps<T>): JSX.Element {
    return (
        <div className="space-y-px p-1">
            {options.map((option) => (
                <LemonButton
                    key={option.key}
                    type="tertiary"
                    size="small"
                    fullWidth
                    role="menuitemcheckbox"
                    aria-checked={selected.includes(option.key)}
                    icon={
                        <LemonCheckbox
                            checked={selected.includes(option.key)}
                            className="pointer-events-none"
                            decorative
                        />
                    }
                    onClick={() =>
                        onChange(
                            selected.includes(option.key)
                                ? selected.filter((value) => value !== option.key)
                                : [...selected, option.key]
                        )
                    }
                >
                    {option.label}
                </LemonButton>
            ))}
        </div>
    )
}

interface SingleSelectOverlayProps<T extends string> {
    options: { value: T; label: string }[]
    selected: T
    onChange: (selected: T) => void
}

function SingleSelectOverlay<T extends string>({
    options,
    selected,
    onChange,
}: SingleSelectOverlayProps<T>): JSX.Element {
    return (
        <div className="space-y-px p-1">
            {options.map((option) => (
                <LemonButton
                    key={option.value}
                    type="tertiary"
                    size="small"
                    fullWidth
                    role="menuitemradio"
                    aria-checked={selected === option.value}
                    onClick={() => onChange(option.value)}
                    active={selected === option.value}
                >
                    {option.label}
                </LemonButton>
            ))}
        </div>
    )
}

function multiSelectSummary<T extends string>(
    options: { key: T; label: string }[],
    selected: T[],
    noun: string
): string {
    if (selected.length === 1) {
        return options.find((option) => option.key === selected[0])?.label ?? selected[0]
    }
    return `${selected.length} ${noun}`
}

function singleSelectSummary<T extends string>(options: { value: T; label: string }[], selected: T): string | null {
    if (selected === 'all') {
        return null
    }
    return options.find((option) => option.value === selected)?.label ?? selected
}

function tagsSummary(include: string[], exclude: string[], match: TicketTagsMatch): string | null {
    if (include.length === 0 && exclude.length === 0) {
        return null
    }
    const parts: string[] = []
    if (include.length === 1) {
        parts.push(include[0])
    } else if (include.length > 1) {
        parts.push(`${match === 'all' ? 'all' : 'any'} of ${include.length} tags`)
    }
    if (exclude.length > 0) {
        parts.push(`excl. ${exclude.length}`)
    }
    return parts.join(', ')
}

export function TicketFilterChip({ filterKey, autoOpen = false }: TicketFilterChipProps): JSX.Element {
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
        dateFrom,
        dateTo,
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
        setDateRange,
    } = useActions(logic)
    const { openFilter, closeFilter } = useActions(ticketFilterBarLogic(logic.props))
    const { tags: tagsAvailable } = useValues(tagsModel)
    const [visible, setVisible] = useState(autoOpen)

    const name = TICKET_FILTER_LABELS[filterKey]

    // The filter bar shows a chip without a value only while its editor is open, so the open
    // state has to reach the logic. If the editor kept it local, clearing the last value would
    // unmount the panel the person is still picking from.
    const setEditorOpen = (open: boolean): void => {
        if (open) {
            openFilter(filterKey)
        } else {
            closeFilter(filterKey)
        }
    }

    // Every chip clears its value and hides itself from the same X, so a chip never lingers
    // after its filter is gone.
    const chipButton = (value: string | null, clear: () => void): JSX.Element => (
        <LemonButton
            type="secondary"
            size="small"
            active={visible}
            {...clearFilterButtonProps(
                () => {
                    clear()
                    closeFilter(filterKey)
                },
                value ? `Clear ${name.toLowerCase()} filter` : 'Remove filter'
            )}
        >
            <span className="flex items-center gap-1">
                <span className={value ? 'text-secondary font-normal' : undefined}>{name}</span>
                {value && <span>{value}</span>}
            </span>
        </LemonButton>
    )

    const dropdown = (overlay: JSX.Element, trigger: JSX.Element, closeOnClickInside = false): JSX.Element => (
        <LemonDropdown
            closeOnClickInside={closeOnClickInside}
            visible={visible}
            onVisibilityChange={(open) => {
                setVisible(open)
                setEditorOpen(open)
            }}
            overlay={overlay}
        >
            {trigger}
        </LemonDropdown>
    )

    switch (filterKey) {
        case 'status':
            return dropdown(
                <MultiSelectOverlay
                    options={statusMultiselectOptions}
                    selected={statusFilter}
                    onChange={setStatusFilter}
                />,
                chipButton(
                    statusFilter.length ? multiSelectSummary(statusMultiselectOptions, statusFilter, 'statuses') : null,
                    () => setStatusFilter([])
                )
            )
        case 'priority':
            return dropdown(
                <MultiSelectOverlay
                    options={priorityMultiselectOptions}
                    selected={priorityFilter}
                    onChange={setPriorityFilter}
                />,
                chipButton(
                    priorityFilter.length
                        ? multiSelectSummary(priorityMultiselectOptions, priorityFilter, 'priorities')
                        : null,
                    () => setPriorityFilter([])
                )
            )
        case 'aiTriageResult':
            return dropdown(
                <MultiSelectOverlay<AITriageFilterValue>
                    options={aiTriageFilterOptions}
                    selected={aiTriageResultFilter}
                    onChange={setAiTriageResultFilter}
                />,
                chipButton(
                    aiTriageResultFilter.length
                        ? multiSelectSummary(aiTriageFilterOptions, aiTriageResultFilter, 'AI results')
                        : null,
                    () => setAiTriageResultFilter([])
                )
            )
        case 'channel':
            return dropdown(
                <SingleSelectOverlay options={channelOptions} selected={channelFilter} onChange={setChannelFilter} />,
                chipButton(singleSelectSummary(channelOptions, channelFilter), () => setChannelFilter('all')),
                true
            )
        case 'sla':
            return dropdown(
                <SingleSelectOverlay<TicketSlaState | 'all'>
                    options={slaOptions}
                    selected={slaFilter}
                    onChange={setSlaFilter}
                />,
                chipButton(singleSelectSummary(slaOptions, slaFilter), () => setSlaFilter('all')),
                true
            )
        case 'tags': {
            const tagOptions = tagsAvailable?.map((tag: string) => ({ key: tag, label: tag })) || []
            const summary = tagsSummary(tagsFilter, tagsExcludeFilter, tagsMatch)
            return dropdown(
                <div className="p-2 min-w-64 flex flex-col gap-2">
                    <div className="flex flex-col gap-1">
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-muted text-xs">Include tags</span>
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
                        <span className="text-muted text-xs">Exclude tags</span>
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
                </div>,
                chipButton(summary, () => {
                    setTagsFilter([])
                    setTagsExcludeFilter([])
                })
            )
        }
        case 'assignee':
            return (
                <AssigneeMultiSelect
                    value={assigneeFilterEntries}
                    onChange={setAssigneeFilter}
                    emptyLabel={name}
                    defaultOpen={autoOpen}
                    onVisibilityChange={setEditorOpen}
                    onRemove={() => closeFilter(filterKey)}
                />
            )
        case 'date':
            return (
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={(from, to) => setDateRange(from, to)}
                    placeholder="All time"
                    size="small"
                />
            )
    }
}
