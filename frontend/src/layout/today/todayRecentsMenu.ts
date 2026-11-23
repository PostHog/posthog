import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { fileSystemTypes } from '~/products'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'
import { FileSystemType } from '~/types'

import { TodayRecent, TodayViewedRecent } from './todayRecents'

export interface TodayRecentsMenuItem {
    href: string
    name: string
    /** The record's own type, such as `insight/funnels` or `person`. */
    type: string
    iconType: string
    /** Lower case, as it reads beside a name: "feature flag", but "SQL insight" keeps its acronym. */
    typeLabel: string
    /** ISO time, or null when the recent was saved before the time was kept. */
    viewedAt: string | null
}

// Records the rail panes keep themselves. File system recents never hold them, except releases, which the file
// system lists without a name.
const LOCAL_RECENT_TYPES: Record<TodayRecent['type'], { label: string; iconType: FileSystemIconType }> = {
    person: { label: 'person', iconType: 'user' },
    group: { label: 'group', iconType: 'group' },
    cohort: { label: 'cohort', iconType: 'cohort' },
    account: { label: 'account', iconType: 'customer_analytics' },
    ticket: { label: 'ticket', iconType: 'conversations' },
    error_tracking_issue: { label: 'issue', iconType: 'error_tracking' },
    logs_view: { label: 'logs view', iconType: 'logs' },
    trace: { label: 'trace', iconType: 'tracing' },
    release: { label: 'release', iconType: 'default_icon_type' },
}

// Tasks are agent sessions rather than things people look at, and releases come from the Release pane's own list.
const SKIPPED_FILE_SYSTEM_TYPES = new Set(['task', 'release'])

function fileSystemType(type: string): FileSystemType | null {
    return Object.hasOwn(fileSystemTypes, type)
        ? (fileSystemTypes[type as keyof typeof fileSystemTypes] as FileSystemType)
        : null
}

function typeLabel(name: string): string {
    return /^[A-Z]{2}/.test(name) ? name : name.charAt(0).toLowerCase() + name.slice(1)
}

/** One key per page, whether or not its href carries the project. */
function pageKey(href: string): string {
    return removeProjectIdIfPresent(href).split('#')[0].replace(/\/+$/, '')
}

function fileSystemItem(entry: FileSystemEntry): TodayRecentsMenuItem | null {
    const baseType = entry.type?.split('/')[0] ?? ''
    if (SKIPPED_FILE_SYSTEM_TYPES.has(baseType)) {
        return null
    }
    const definition = fileSystemType(baseType)
    const href = entry.href || (entry.ref && definition?.href ? definition.href(entry.ref) : null)
    const name = splitPath(entry.path).pop()
    if (!href || !name) {
        return null
    }
    return {
        href,
        name,
        type: entry.type ?? baseType,
        iconType: entry.type ?? baseType,
        typeLabel: definition ? typeLabel(definition.name) : baseType.replace(/_/g, ' '),
        viewedAt: entry.last_viewed_at ?? null,
    }
}

function localItem(recent: TodayViewedRecent<TodayRecent>): TodayRecentsMenuItem {
    const { label, iconType } = LOCAL_RECENT_TYPES[recent.type]
    return {
        href: recent.href,
        name: recent.name,
        type: recent.type,
        iconType,
        typeLabel: label,
        viewedAt: recent.viewedAt ? new Date(recent.viewedAt).toISOString() : null,
    }
}

function viewedTime(item: TodayRecentsMenuItem): number {
    return item.viewedAt ? Date.parse(item.viewedAt) : 0
}

/**
 * Everything a person opened, from every rail pane, newest first. A page in more than one list shows once, with its
 * latest visit. Items without a time come last.
 */
export function todayRecentsMenuItems(
    fileSystemRecents: FileSystemEntry[],
    localRecents: TodayViewedRecent<TodayRecent>[]
): TodayRecentsMenuItem[] {
    const byPage = new Map<string, TodayRecentsMenuItem>()
    const items = [...fileSystemRecents.map(fileSystemItem), ...localRecents.map(localItem)].filter(
        (item): item is TodayRecentsMenuItem => item !== null
    )
    for (const item of items) {
        const key = pageKey(item.href)
        const current = byPage.get(key)
        if (!current || viewedTime(item) > viewedTime(current)) {
            byPage.set(key, item)
        }
    }
    return [...byPage.values()].sort((first, second) => viewedTime(second) - viewedTime(first))
}
