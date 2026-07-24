import { Dayjs } from 'lib/dayjs'
import { compareTimeTreeItems } from 'lib/utils/time-tree'

export enum ItemCategory {
    ERROR_TRACKING = 'exceptions',
    EXCEPTION_STEPS = 'exception steps',
    CUSTOM_EVENTS = 'custom events',
    PAGE_VIEWS = 'pageviews',
    CONSOLE_LOGS = 'console logs',
}

export interface TimelineItem {
    id: string
    category: ItemCategory
    timestamp: Dayjs
    payload: any
    sortPriority?: number
}

export function compareTimelineItems(a: TimelineItem, b: TimelineItem): number {
    return compareTimeTreeItems(a, b)
}

export interface RendererProps<T extends TimelineItem> {
    item: T
    sessionId?: string
}

export interface TimelineMenuItem {
    key: string
    label: string
    onClick: () => void
}

export type ItemRenderer<T extends TimelineItem> = {
    sourceIcon: React.FC<RendererProps<T>>
    categoryIcon: React.ReactNode
    render: React.FC<RendererProps<T>>
    renderExpanded?: React.FC<RendererProps<T>>
    getMenuItems?: (props: RendererProps<T>) => TimelineMenuItem[]
}

export interface LoaderBatch<T extends TimelineItem> {
    items: T[]
    hasMoreBefore?: boolean
    hasMoreAfter?: boolean
}

/**
 * Paginated loader for timeline items. Each call returns up to `limit` items
 * before/after the given cursor, within a fixed time window around the center.
 */
export type ItemLoader<T extends TimelineItem> = {
    loadBefore(cursor: Dayjs, limit: number): Promise<LoaderBatch<T>>
    loadAfter(cursor: Dayjs, limit: number): Promise<LoaderBatch<T>>
}

// eslint-disable-next-line import/no-cycle
export * from './item-collector'
