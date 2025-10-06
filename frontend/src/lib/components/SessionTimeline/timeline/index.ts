import { Dayjs } from 'lib/dayjs'

export enum ItemCategory {
    ERROR_TRACKING = 'exceptions',
    CUSTOM_EVENTS = 'custom events',
    PAGE_VIEWS = 'pageviews',
}

export interface TimelineItem {
    id: string
    category: ItemCategory
    timestamp: Dayjs
    payload: any
}

export interface RendererProps<T extends TimelineItem> {
    item: T
}

export type ItemRenderer<T extends TimelineItem> = {
    sourceIcon: React.FC<RendererProps<T>>
    categoryIcon: React.ReactNode
    render: React.FC<RendererProps<T>>
}

export type ItemLoader<T extends TimelineItem> = {
    hasPrevious(index: Dayjs): boolean
    previous(index: Dayjs, limit?: number): Promise<T | null>

    hasNext(index: Dayjs): boolean
    next(index: Dayjs, limit?: number): Promise<T | null>
}

export type ItemLoaderFactory<T extends TimelineItem> = (sessionId: string, timestamp: Dayjs) => ItemLoader<T>
export * from './item-collector'
