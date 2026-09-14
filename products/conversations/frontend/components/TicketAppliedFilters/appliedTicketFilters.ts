import { useMountedLogic, useValues } from 'kea'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import {
    type AITriageFilterValue,
    type TicketChannel,
    type TicketPriority,
    type TicketSlaState,
    type TicketStatus,
    type TicketTagsMatch,
    aiTriageFilterOptions,
    channelOptions,
    priorityMultiselectOptions,
    slaOptions,
    statusMultiselectOptions,
} from '../../types'
import type { AssigneeFilterEntry } from '../Assignee/types'

export type AppliedTicketFilter =
    | { key: string; kind: 'status'; value: TicketStatus; label: string }
    | { key: string; kind: 'priority'; value: TicketPriority; label: string }
    | { key: string; kind: 'channel'; label: string }
    | { key: string; kind: 'sla'; label: string }
    | { key: string; kind: 'ai'; value: AITriageFilterValue; label: string }
    | { key: string; kind: 'tag'; value: string; label: string }
    | { key: string; kind: 'tag-exclude'; value: string; label: string }
    | { key: string; kind: 'assignee'; entry: AssigneeFilterEntry }

export interface AppliedTicketFiltersState {
    statusFilter: TicketStatus[]
    priorityFilter: TicketPriority[]
    channelFilter: TicketChannel | 'all'
    slaFilter: TicketSlaState | 'all'
    aiTriageResultFilter: AITriageFilterValue[]
    assigneeFilterEntries: AssigneeFilterEntry[]
    tagsFilter: string[]
    tagsMatch: TicketTagsMatch
    tagsExcludeFilter: string[]
}

export function listAppliedTicketFilters(state: AppliedTicketFiltersState): AppliedTicketFilter[] {
    const chips: AppliedTicketFilter[] = []

    for (const status of state.statusFilter) {
        const label = statusMultiselectOptions.find((option) => option.key === status)?.label ?? status
        chips.push({ key: `status:${status}`, kind: 'status', value: status, label: `Status: ${label}` })
    }

    for (const priority of state.priorityFilter) {
        const label = priorityMultiselectOptions.find((option) => option.key === priority)?.label ?? priority
        chips.push({ key: `priority:${priority}`, kind: 'priority', value: priority, label: `Priority: ${label}` })
    }

    if (state.channelFilter !== 'all') {
        const label =
            channelOptions.find((option) => option.value === state.channelFilter)?.label ?? state.channelFilter
        chips.push({ key: `channel:${state.channelFilter}`, kind: 'channel', label: `Channel: ${label}` })
    }

    if (state.slaFilter !== 'all') {
        const label = slaOptions.find((option) => option.value === state.slaFilter)?.label ?? state.slaFilter
        chips.push({ key: `sla:${state.slaFilter}`, kind: 'sla', label: `SLA: ${label}` })
    }

    for (const result of state.aiTriageResultFilter) {
        const label = aiTriageFilterOptions.find((option) => option.key === result)?.label ?? result
        chips.push({ key: `ai:${result}`, kind: 'ai', value: result, label: `AI result: ${label}` })
    }

    const tagPrefix = state.tagsMatch === 'all' ? 'Tag (all)' : 'Tag'
    for (const tag of state.tagsFilter) {
        chips.push({ key: `tag:${tag}`, kind: 'tag', value: tag, label: `${tagPrefix}: ${tag}` })
    }

    for (const tag of state.tagsExcludeFilter) {
        chips.push({
            key: `tag-exclude:${tag}`,
            kind: 'tag-exclude',
            value: tag,
            label: `Excluded tag: ${tag}`,
        })
    }

    for (const entry of state.assigneeFilterEntries) {
        chips.push({ key: assigneeChipKey(entry), kind: 'assignee', entry })
    }

    return chips
}

export function useAppliedTicketFilters(): AppliedTicketFilter[] {
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
    } = useValues(logic)

    return listAppliedTicketFilters({
        statusFilter,
        priorityFilter,
        channelFilter,
        slaFilter,
        aiTriageResultFilter,
        assigneeFilterEntries,
        tagsFilter,
        tagsMatch,
        tagsExcludeFilter,
    })
}

function assigneeChipKey(entry: AssigneeFilterEntry): string {
    return typeof entry === 'string' ? `assignee:${entry}` : `assignee:${entry.type}:${entry.id}`
}
