import { ItemCategory, ItemLoader, ItemRenderer, TimelineItem } from '.'

import { Dayjs } from 'lib/dayjs'
import { TimeTree } from 'lib/utils/time-tree'

export class ItemCollector {
    sessionId: string
    timestamp: Dayjs
    beforeCursor: Dayjs
    afterCursor: Dayjs
    itemCache: TimeTree<TimelineItem>
    loaders: Map<ItemCategory, ItemLoader<TimelineItem>> = new Map()
    renderers: Map<ItemCategory, ItemRenderer<TimelineItem>> = new Map()

    constructor(sessionId: string, timestamp: Dayjs) {
        this.sessionId = sessionId
        this.timestamp = timestamp
        this.beforeCursor = this.timestamp
        this.afterCursor = this.timestamp
        this.itemCache = new TimeTree<TimelineItem>()
    }

    addCategory(category: ItemCategory, renderer: ItemRenderer<TimelineItem>, loader: ItemLoader<TimelineItem>): void {
        this.loaders.set(category, loader)
        this.renderers.set(category, renderer)
    }

    getAllCategories(): ItemCategory[] {
        return Array.from(this.loaders.keys())
    }

    findMinTimestamp(array: TimelineItem[]): TimelineItem {
        return array.slice().sort((a, b) => a.timestamp.diff(b.timestamp))[0]
    }

    findMaxTimestamp(array: TimelineItem[]): TimelineItem {
        return array.slice().sort((a, b) => b.timestamp.diff(a.timestamp))[0]
    }

    clear(): void {
        this.beforeCursor = this.timestamp
        this.afterCursor = this.timestamp
        this.itemCache = new TimeTree<TimelineItem>()
    }

    getRenderer(category: ItemCategory): ItemRenderer<TimelineItem> | undefined {
        return this.renderers.get(category)
    }

    getLoader(category: ItemCategory): ItemLoader<TimelineItem> | undefined {
        return this.loaders.get(category)
    }

    getCategories(): ItemCategory[] {
        return Array.from(this.loaders.keys())
    }

    collectItems(): TimelineItem[] {
        return this.itemCache.getAll()
    }

    hasBefore(categories: ItemCategory[]): boolean {
        return categories
            .map((cat) => this.getLoader(cat))
            .some((loader) => !!loader && loader.hasPrevious(this.beforeCursor))
    }

    hasAfter(categories: ItemCategory[]): boolean {
        return categories
            .map((cat) => this.getLoader(cat))
            .some((loader) => !!loader && loader.hasNext(this.afterCursor))
    }

    async loadBefore(categories: ItemCategory[], count: number): Promise<void> {
        const items = []
        let currentLoaders = categories
            .map((cat) => this.getLoader(cat))
            .filter((loader) => !!loader) as ItemLoader<TimelineItem>[]

        while (items.length < count) {
            const previousItems = await Promise.all(
                currentLoaders.map((loader) => loader.previous(this.beforeCursor, count))
            )
            const maxItem = this.findMaxTimestamp(previousItems.filter((item) => item !== null) as TimelineItem[])
            if (maxItem) {
                items.push(maxItem)
                this.beforeCursor = maxItem.timestamp
            } else {
                break
            }
        }
        this.itemCache.add(items)
    }

    async loadAfter(categories: ItemCategory[], count: number): Promise<void> {
        const items = []
        let currentLoaders = categories
            .map((cat) => this.getLoader(cat))
            .filter((loader) => !!loader) as ItemLoader<TimelineItem>[]
        while (items.length < count) {
            const nextItems = await Promise.all(currentLoaders.map((loader) => loader.next(this.afterCursor, count)))
            const minItem = this.findMinTimestamp(nextItems.filter((item) => item !== null) as TimelineItem[])
            if (minItem) {
                items.push(minItem)
                this.afterCursor = minItem.timestamp
            } else {
                break
            }
        }
        this.itemCache.add(items)
    }
}
