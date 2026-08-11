import { useEffect, useState } from 'react'

import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { AssigneeMultiSelect, type AssigneeFilterEntry } from 'products/conversations/frontend/components/Assignee'

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
} from './conversationsWidgetConfigValidation'

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
        <LemonInput
            size="small"
            type="search"
            className="min-w-48"
            value={draft}
            placeholder="Requester, subject, or message"
            onChange={setDraft}
            onBlur={() => onChange(draft)}
        />
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
            <LemonSelect
                size="small"
                value={status}
                options={CONVERSATIONS_TICKET_STATUS_OPTIONS}
                onChange={(value) => {
                    if (value) {
                        const nextConfig = patchConversationsWidgetConfig(getLatestConfig(), { status: value })
                        void persistConfigNow(nextConfig)
                    }
                }}
            />
            <LemonInputSelect
                size="small"
                mode="multiple"
                value={priorities}
                options={CONVERSATIONS_TICKET_PRIORITY_OPTIONS}
                placeholder="All priorities"
                onChange={(value) => {
                    const nextConfig = patchConversationsWidgetConfig(getLatestConfig(), { priorities: value })
                    void persistConfigNow(nextConfig)
                }}
            />
            <LemonSelect
                size="small"
                value={channel}
                options={CONVERSATIONS_TICKET_CHANNEL_OPTIONS}
                onChange={(value) => {
                    const nextConfig = patchConversationsWidgetConfig(getLatestConfig(), { channel: value })
                    void persistConfigNow(nextConfig)
                }}
            />
            <AssigneeMultiSelect
                value={assignees}
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
        </WidgetTileFiltersBar>
    )
}
