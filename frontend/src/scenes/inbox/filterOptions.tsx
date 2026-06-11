import { JSX } from 'react'

import {
    IconBolt,
    IconBrain,
    IconBug,
    IconCalendar,
    IconClock,
    IconCompass,
    IconDatabase,
    IconGithub,
    IconList,
    IconReceipt,
    IconRewindPlay,
    IconStack,
    IconSupport,
} from '@posthog/icons'

import { InboxSortDirection, InboxSortField } from './logics/inboxFiltersLogic'
import { SignalReportPriority } from './types'

// Port of desktop `@posthog/ui/features/inbox/filterOptions`. Drives the Source /
// Sort / Priority filter popovers. Source-product values match the backend
// `source_product` values; priority values are P0–P4.

export interface InboxSortOption {
    label: string
    field: InboxSortField
    direction: InboxSortDirection
    icon: JSX.Element
}

export const INBOX_SORT_OPTIONS: InboxSortOption[] = [
    { label: 'Priority first', field: 'priority', direction: 'asc', icon: <IconList /> },
    { label: 'Strongest evidence', field: 'total_weight', direction: 'desc', icon: <IconBolt /> },
    { label: 'Newest first', field: 'created_at', direction: 'desc', icon: <IconCalendar /> },
    { label: 'Oldest first', field: 'created_at', direction: 'asc', icon: <IconClock /> },
]

export const INBOX_PRIORITY_OPTIONS: { value: SignalReportPriority; accent: string }[] = [
    { value: 'P0', accent: 'var(--red-9, #e5484d)' },
    { value: 'P1', accent: 'var(--orange-9, #f76b15)' },
    { value: 'P2', accent: 'var(--amber-9, #ffc53d)' },
    { value: 'P3', accent: 'var(--muted, #8f8f8f)' },
    { value: 'P4', accent: 'var(--muted, #8f8f8f)' },
]

export const INBOX_SOURCE_OPTIONS: { value: string; label: string; icon: JSX.Element }[] = [
    { value: 'session_replay', label: 'Session replay', icon: <IconRewindPlay /> },
    { value: 'error_tracking', label: 'Error tracking', icon: <IconBug /> },
    { value: 'llm_analytics', label: 'AI observability', icon: <IconBrain /> },
    { value: 'github', label: 'GitHub', icon: <IconGithub /> },
    { value: 'linear', label: 'Linear', icon: <IconStack /> },
    { value: 'zendesk', label: 'Zendesk', icon: <IconReceipt /> },
    { value: 'conversations', label: 'Conversations', icon: <IconSupport /> },
    { value: 'pganalyze', label: 'pganalyze', icon: <IconDatabase /> },
    { value: 'signals_scout', label: 'Scout', icon: <IconCompass /> },
]

export function inboxSortOptionKey(field: InboxSortField, direction: InboxSortDirection): string {
    return `${field}:${direction}`
}

export function inboxSourceFilterLabel(selected: string[]): string {
    if (selected.length === 0) {
        return 'All sources'
    }
    if (selected.length === 1) {
        return INBOX_SOURCE_OPTIONS.find((o) => o.value === selected[0])?.label ?? selected[0]
    }
    return `${selected.length} sources`
}

export function inboxPriorityFilterLabel(selected: SignalReportPriority[]): string {
    if (selected.length === 0) {
        return 'All priorities'
    }
    if (selected.length <= 2) {
        return selected.join(', ')
    }
    return `${selected.length} priorities`
}
