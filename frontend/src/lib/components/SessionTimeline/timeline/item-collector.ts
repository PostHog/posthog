import { Dayjs } from 'lib/dayjs'
import { TimeTree } from 'lib/utils/time-tree'

// eslint-disable-next-line import/no-cycle
import { compareTimelineItems, ItemCategory, ItemLoader, ItemRenderer, LoaderBatch, TimelineItem } from '.'

type LoaderState = {
    hasMoreBefore: boolean
    hasMoreAfter: boolean
}

export class ItemCollector {
    readonly sessionId: string
    readonly timestamp: Dayjs

    private beforeCursor: Dayjs
    private afterCursor: Dayjs
    private _hasMoreBefore = true
    private _hasMoreAfter = true
    private itemCache: TimeTree<TimelineItem>

    private loaders = new Set<ItemLoader<TimelineItem>>()
    private loaderState = new Map<ItemLoader<TimelineItem>, LoaderState>()
    private renderers = new Map<ItemCategory, ItemRenderer<TimelineItem>>()

    constructor(sessionId: string, timestamp: Dayjs) {
        this.sessionId = sessionId
        this.timestamp = timestamp
        this.beforeCursor = timestamp
        this.afterCursor = timestamp
        this.itemCache = new TimeTree<TimelineItem>()
    }

    /**
     * Register a category with its renderer and loader.
     * The same loader instance may be shared across categories — it will only be
     * called once per load (Set deduplicates by identity).
     */
    addCategory(category: ItemCategory, renderer: ItemRenderer<TimelineItem>, loader: ItemLoader<TimelineItem>): void {
        this.renderers.set(category, renderer)
        this.loaders.add(loader)
        if (!this.loaderState.has(loader)) {
            this.loaderState.set(loader, {
                hasMoreBefore: true,
                hasMoreAfter: true,
            })
        }
    }

    getAllCategories(): ItemCategory[] {
        return Array.from(this.renderers.keys())
    }

    getRenderer(category: ItemCategory): ItemRenderer<TimelineItem> | undefined {
        return this.renderers.get(category)
    }

    collectItems(): TimelineItem[] {
        return this.itemCache.getAll()
    }

    get hasMoreBefore(): boolean {
        return this._hasMoreBefore
    }

    get hasMoreAfter(): boolean {
        return this._hasMoreAfter
    }

    clear(): void {
        this.beforeCursor = this.timestamp
        this.afterCursor = this.timestamp
        this._hasMoreBefore = true
        this._hasMoreAfter = true
        this.itemCache = new TimeTree<TimelineItem>()
        this.loaderState.forEach((state) => {
            state.hasMoreBefore = true
            state.hasMoreAfter = true
        })
    }

    async loadBefore(count: number): Promise<void> {
        if (!this._hasMoreBefore) {
            return
        }

        const loaders = Array.from(this.loaders).filter((loader) => this.loaderState.get(loader)?.hasMoreBefore)
        if (loaders.length === 0) {
            this._hasMoreBefore = false
            return
        }

        const perLoader = Math.max(1, Math.ceil(count / loaders.length))

        const batches = await Promise.all(
            loaders.map(async (loader) => {
                const batch = this.normalizeLoaderResult(await loader.loadBefore(this.beforeCursor, perLoader))
                this.updateLoaderDirection(loader, 'before', batch.hasMoreBefore ?? false)
                return batch
            })
        )

        const allItems = batches.flatMap((batch) => batch.items).sort((a, b) => compareTimelineItems(b, a))
        const selected = allItems.slice(0, count)

        if (selected.length > 0) {
            // Keep a 1 ms overlap so strict `isBefore(cursor)` loaders don't skip
            // sibling items that share the exact same boundary timestamp.
            this.beforeCursor = selected[selected.length - 1].timestamp.add(1, 'millisecond')
        }

        this.itemCache.add(selected)
        this._hasMoreBefore = Array.from(this.loaderState.values()).some((state) => state.hasMoreBefore)
    }

    async loadAfter(count: number): Promise<void> {
        if (!this._hasMoreAfter) {
            return
        }

        const loaders = Array.from(this.loaders).filter((loader) => this.loaderState.get(loader)?.hasMoreAfter)
        if (loaders.length === 0) {
            this._hasMoreAfter = false
            return
        }

        const perLoader = Math.max(1, Math.ceil(count / loaders.length))

        const batches = await Promise.all(
            loaders.map(async (loader) => {
                const batch = this.normalizeLoaderResult(await loader.loadAfter(this.afterCursor, perLoader))
                this.updateLoaderDirection(loader, 'after', batch.hasMoreAfter ?? false)
                return batch
            })
        )

        const allItems = batches.flatMap((batch) => batch.items).sort(compareTimelineItems)
        const selected = allItems.slice(0, count)

        if (selected.length > 0) {
            // Keep a 1 ms overlap so strict `isAfter(cursor)` loaders don't skip
            // sibling items that share the exact same boundary timestamp.
            this.afterCursor = selected[selected.length - 1].timestamp.subtract(1, 'millisecond')
        }

        this.itemCache.add(selected)
        this._hasMoreAfter = Array.from(this.loaderState.values()).some((state) => state.hasMoreAfter)
    }

    private updateLoaderDirection(
        loader: ItemLoader<TimelineItem>,
        direction: 'before' | 'after',
        hasMore: boolean
    ): void {
        const state = this.loaderState.get(loader)
        if (!state) {
            return
        }

        if (direction === 'before') {
            state.hasMoreBefore = hasMore
        } else {
            state.hasMoreAfter = hasMore
        }
    }

    private normalizeLoaderResult(result: LoaderBatch<TimelineItem>): LoaderBatch<TimelineItem> {
        return {
            items: result.items,
            hasMoreBefore: result.hasMoreBefore,
            hasMoreAfter: result.hasMoreAfter,
        }
    }
}
