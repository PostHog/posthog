import { useEffect, useState } from 'react'

import { IconSearch } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { AssigneeMultiSelect, type AssigneeFilterEntry } from 'products/conversations/frontend/components/Assignee'
import { clearFilterButtonProps } from 'products/conversations/frontend/components/clearFilterButtonProps'

import type { DashboardWidgetTileFiltersProps } from '../registry'
import { useWidgetTileConfigPersist } from '../widgetTileFiltersHooks'
import { WidgetTileFilterReadOnlyLabel, WidgetTileFiltersBar } from '../widgetTileFiltersReadOnly'
import {
    CONVERSATIONS_TICKET_CHANNEL_OPTIONS,
    CONVERSATIONS_TICKET_PRIORITY_OPTIONS,
    CONVERSATIONS_TICKET_STATUS_OPTIONS,
    type ConversationsTicketAssignee,
    parseConversationsWidgetConfig,
    patchConversationsWidgetConfig,
    type ConversationsTicketPriority,
} from './conversationsWidgetConfigValidation'

function priorityFilterLabel(priorities: ConversationsTicketPriority[]): string {
    if (priorities.length === 0) {
        return 'Priority'
    }
    if (priorities.length === 1) {
        return (
            CONVERSATIONS_TICKET_PRIORITY_OPTIONS.find((option) => option.key === priorities[0])?.label ?? priorities[0]
        )
    }
    return `${priorities.length} priorities`
}

function ConversationsPriorityFilter({
    value,
    onChange,
}: {
    value: ConversationsTicketPriority[]
    onChange: (value: ConversationsTicketPriority[]) => void
}): JSX.Element {
    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <div className="space-y-px p-1">
                    {CONVERSATIONS_TICKET_PRIORITY_OPTIONS.map((option) => (
                        <LemonButton
                            key={option.key}
                            type="tertiary"
                            size="small"
                            fullWidth
                            icon={
                                <LemonCheckbox checked={value.includes(option.key)} className="pointer-events-none" />
                            }
                            onClick={() => {
                                const nextValue = value.includes(option.key)
                                    ? value.filter((priority) => priority !== option.key)
                                    : [...value, option.key]
                                onChange(nextValue)
                            }}
                        >
                            {option.label}
                        </LemonButton>
                    ))}
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                {...clearFilterButtonProps(value.length > 0 ? () => onChange([]) : null, 'Clear priority filter')}
            >
                {priorityFilterLabel(value)}
            </LemonButton>
        </LemonDropdown>
    )
}

function ConversationsSearchFilter({
    value,
    onChange,
}: {
    value: string
    onChange: (value: string) => void
}): JSX.Element {
    const [draft, setDraft] = useState(value)

    useEffect(() => {
        setDraft(value)
    }, [value])

    return (
        <LemonDropdown
            overlay={
                <LemonInput
                    size="small"
                    type="search"
                    className="w-80"
                    value={draft}
                    placeholder="Requester, subject, or message"
                    onChange={setDraft}
                    onBlur={() => onChange(draft)}
                    autoFocus
                />
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconSearch />}
                {...clearFilterButtonProps(value ? () => onChange('') : null, 'Clear search filter')}
            >
                Search
            </LemonButton>
        </LemonDropdown>
    )
}

export function ConversationsWidgetTileFilters({
    config,
    onUpdateConfig,
    disabledReason,
}: DashboardWidgetTileFiltersProps): JSX.Element {
    const parsedConfig = parseConversationsWidgetConfig(config)
    const status = parsedConfig.status ?? 'all'
    const priorities = parsedConfig.priorities ?? []
    const channel = parsedConfig.channel ?? 'all'
    const assignees = (parsedConfig.assignees ?? []) as AssigneeFilterEntry[]
    const search = parsedConfig.search ?? ''
    const { getLatestConfig, persistConfigNow } = useWidgetTileConfigPersist(onUpdateConfig, config)
    const statusLabel = CONVERSATIONS_TICKET_STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status
    const channelLabel =
        CONVERSATIONS_TICKET_CHANNEL_OPTIONS.find((option) => option.value === channel)?.label ?? channel
    const prioritiesLabel = priorities.length === 0 ? 'All priorities' : `${priorities.length} selected`
    const assigneesLabel = assignees.length === 0 ? 'All assignees' : `${assignees.length} selected`

    if (!onUpdateConfig || disabledReason) {
        return (
            <WidgetTileFiltersBar dataAttr="conversations-widget-filters-readonly">
                <WidgetTileFilterReadOnlyLabel name="Status" value={statusLabel} />
                <WidgetTileFilterReadOnlyLabel name="Priority" value={prioritiesLabel} />
                <WidgetTileFilterReadOnlyLabel name="Channel" value={channelLabel} />
                <WidgetTileFilterReadOnlyLabel name="Assignee" value={assigneesLabel} />
                {search ? <WidgetTileFilterReadOnlyLabel name="Search" value={search} /> : null}
            </WidgetTileFiltersBar>
        )
    }
    return (
        <WidgetTileFiltersBar dataAttr="conversations-widget-filters">
            <div className="flex w-full min-w-0 flex-nowrap items-center gap-2">
                <LemonSelect
                    size="small"
                    value={status}
                    options={CONVERSATIONS_TICKET_STATUS_OPTIONS}
                    renderButtonContent={(option) => (option?.value === 'all' ? 'Status' : (option?.label ?? 'Status'))}
                    onChange={(value) => {
                        if (value) {
                            const nextConfig = patchConversationsWidgetConfig(getLatestConfig(), { status: value })
                            void persistConfigNow(nextConfig)
                        }
                    }}
                />
                <ConversationsPriorityFilter
                    value={priorities}
                    onChange={(value) => {
                        const nextConfig = patchConversationsWidgetConfig(getLatestConfig(), { priorities: value })
                        void persistConfigNow(nextConfig)
                    }}
                />
                <LemonSelect
                    size="small"
                    value={channel}
                    options={CONVERSATIONS_TICKET_CHANNEL_OPTIONS}
                    renderButtonContent={(option) =>
                        option?.value === 'all' ? 'Channel' : (option?.label ?? 'Channel')
                    }
                    onChange={(value) => {
                        const nextConfig = patchConversationsWidgetConfig(getLatestConfig(), { channel: value })
                        void persistConfigNow(nextConfig)
                    }}
                />
                <AssigneeMultiSelect
                    value={assignees}
                    emptyLabel="Assignee"
                    onChange={(value) => {
                        const nextConfig = patchConversationsWidgetConfig(getLatestConfig(), {
                            assignees: value as ConversationsTicketAssignee[],
                        })
                        void persistConfigNow(nextConfig)
                    }}
                />
                <ConversationsSearchFilter
                    value={search}
                    onChange={(value) => {
                        const nextConfig = patchConversationsWidgetConfig(getLatestConfig(), { search: value })
                        void persistConfigNow(nextConfig)
                    }}
                />
            </div>
        </WidgetTileFiltersBar>
    )
}
