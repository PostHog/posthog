import { JSX } from 'react'

import {
    IconBrain,
    IconBug,
    IconCalendar,
    IconClock,
    IconCompass,
    IconDatabase,
    IconGithub,
    IconList,
    IconReceipt,
    IconRefresh,
    IconRewindPlay,
    IconStack,
    IconSupport,
} from '@posthog/icons'
import { LemonTagType } from '@posthog/lemon-ui'

import { InboxSortDirection, InboxSortField } from './logics/inboxFiltersLogic'
import { SignalReportPriority } from './types'

/**
 * Single source of truth for per-priority color. P0–P4 each get a DISTINCT hue so
 * users can tell them apart at a glance (red → orange → amber → blue → gray).
 * Consumed by the priority badge, the priority monogram, and the filter dots.
 */
export const PRIORITY_TAG_TYPE: Record<SignalReportPriority, LemonTagType> = {
    P0: 'danger', // red
    P1: 'warning', // orange
    P2: 'caution', // amber
    P3: 'highlight', // blue
    P4: 'muted', // gray
}

/**
 * Human meaning of each priority code, mirroring the criteria the research agent judges against
 * (see products/signals/backend/report_generation/research.py). Surfaced in the priority badge
 * tooltip and the priority filter so users don't have to guess what P0–P4 mean.
 */
export const PRIORITY_MEANING: Record<SignalReportPriority, { label: string; description: string }> = {
    P0: {
        label: 'Critical',
        description: 'Production errors, a broken core flow, data loss, or a security vulnerability.',
    },
    P1: { label: 'High', description: 'Significant user-facing impact or a clear regression.' },
    P2: { label: 'Medium', description: 'A clear improvement opportunity, or a contained issue with workarounds.' },
    P3: { label: 'Low', description: 'A minor improvement or low-impact issue.' },
    P4: { label: 'Minimal', description: 'Cosmetic or negligible impact, or an optional investigation.' },
}

/** Matching CSS accent per priority, for non-LemonTag surfaces (filter dots, monograms). */
export const PRIORITY_ACCENT: Record<SignalReportPriority, string> = {
    P0: 'var(--red-9, #e5484d)',
    P1: 'var(--orange-9, #f76b15)',
    P2: 'var(--amber-9, #ffc53d)',
    P3: 'var(--blue-9, #3b9eff)',
    P4: 'var(--muted, #8f8f8f)',
}

// Port of desktop `@posthog/ui/features/inbox/filterOptions`. Drives the Source /
// Sort filter popovers. Source-product values match the backend
// `source_product` values.

export interface InboxSortOption {
    label: string
    field: InboxSortField
    direction: InboxSortDirection
    icon: JSX.Element
}

export const INBOX_SORT_OPTIONS: InboxSortOption[] = [
    { label: 'Priority first', field: 'priority', direction: 'asc', icon: <IconList /> },
    { label: 'Last updated first', field: 'updated_at', direction: 'desc', icon: <IconRefresh /> },
    { label: 'Newest first', field: 'created_at', direction: 'desc', icon: <IconCalendar /> },
    { label: 'Oldest first', field: 'created_at', direction: 'asc', icon: <IconClock /> },
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

/** Priority codes in rank order (P0 highest → P4 lowest), driving the Priority filter popover. */
export const INBOX_PRIORITY_OPTIONS: SignalReportPriority[] = ['P0', 'P1', 'P2', 'P3', 'P4']

export function inboxSortOptionKey(field: InboxSortField, direction: InboxSortDirection): string {
    return `${field}:${direction}`
}

export function inboxPriorityFilterLabel(selected: SignalReportPriority[]): string {
    if (selected.length === 0) {
        return 'All priorities'
    }
    // Codes are short (P0–P4), so list them in rank order rather than collapsing to a count.
    return [...selected].sort().join(', ')
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
