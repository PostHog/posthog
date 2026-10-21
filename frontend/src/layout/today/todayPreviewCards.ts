import { libraryObjectHref, libraryObjectName, libraryTypeLabel } from 'scenes/library/libraryUtils'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { SidebarProductMeta, sidebarProductMeta } from '~/layout/panel-layout/sidebarProductMeta'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'

import { getOriginProductMeta } from 'products/posthog_ai/frontend/api/taskSource'
import { PrStateEnumApi, TaskUserBasicInfoApi } from 'products/tasks/frontend/generated/api.schemas'
import { TaskPullRequest } from 'products/tasks/frontend/spaces/taskPullRequests'

import { recentSourceLabel } from './todayRecentFilters'
import { TodaySessionDot, todaySessionDot } from './todaySessionDot'
import { TodaySessionMenuTarget, TodayWorkItem, sessionMenuTarget } from './todayWorkItems'

/** What a session row's hover card says, built once per row so the shared card gets a stable payload. */
export interface TodaySessionPreview {
    kind: 'session'
    title: string
    dot: TodaySessionDot
    pinned: boolean
    pullRequest: TaskPullRequest | null
    pullRequestState: PrStateEnumApi | null
    spaceName: string | null
    repository: string | null
    branch: string | null
    /** What filed the session, or null when a person made it by hand. */
    source: string | null
    /** The source product's icon, for the origins that have one. */
    sourceIcon: JSX.Element | null
    author: TaskUserBasicInfoApi | null
    timestamp: string | null
    message: string | null
    menu: TodaySessionMenuTarget
}

export interface TodayChatPreview {
    kind: 'chat'
    chatId: string
    title: string
    source: string
    timestamp: string | null
}

export interface TodayObjectPreview {
    kind: 'object'
    name: string
    type: string | undefined
    ref: string | null
    typeLabel: string | null
    folder: string[]
    href: string | null
    lastViewedAt: string | null
}

export interface TodayProductPreview extends SidebarProductMeta {
    kind: 'product'
    label: string
    product: FileSystemImport
}

export type TodayPreviewPayload = TodaySessionPreview | TodayChatPreview | TodayObjectPreview | TodayProductPreview

export function sessionPreview(
    item: TodayWorkItem,
    {
        unread,
        pinned,
        pullRequestStates,
        spaceNames,
        menuId,
        userId,
    }: {
        unread: boolean
        pinned: boolean
        pullRequestStates: Record<string, PrStateEnumApi>
        spaceNames: Record<string, string>
        menuId: string
        userId: number | null | undefined
    }
): TodaySessionPreview {
    // The row shows only the first pull request, so the card names the same one.
    const [pullRequest] = item.pullRequests
    return {
        kind: 'session',
        title: item.title || 'Untitled session',
        dot: todaySessionDot(item, unread),
        pinned,
        pullRequest: pullRequest ?? null,
        pullRequestState: pullRequest ? (pullRequestStates[pullRequest.url] ?? null) : null,
        spaceName: item.channel ? (spaceNames[item.channel] ?? null) : null,
        repository: item.repository,
        branch: item.branch,
        source:
            item.originProduct && item.originProduct !== 'user_created' ? recentSourceLabel(item.originProduct) : null,
        sourceIcon: getOriginProductMeta(item.originProduct ?? undefined)?.icon ?? null,
        author: item.author,
        timestamp: item.timestamp,
        message: item.finalMessage,
        menu: sessionMenuTarget(item, { menuId, pinned, userId }),
    }
}

export function objectPreview(entry: FileSystemEntry): TodayObjectPreview {
    return {
        kind: 'object',
        name: libraryObjectName(entry),
        type: entry.type,
        ref: entry.ref ?? null,
        typeLabel: libraryTypeLabel(entry.type),
        folder: splitPath(entry.path).slice(0, -1),
        href: libraryObjectHref(entry),
        lastViewedAt: entry.last_viewed_at ?? null,
    }
}

export function chatPreview(item: TodayWorkItem): TodayChatPreview {
    return {
        kind: 'chat',
        chatId: item.id,
        title: item.title || 'Untitled chat',
        source: 'PostHog AI',
        timestamp: item.timestamp,
    }
}

export function productPreview(label: string, product: FileSystemImport): TodayProductPreview {
    return { kind: 'product', label, product, ...sidebarProductMeta(product) }
}
