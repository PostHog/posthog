import { ItemCache, ItemLoader, TimelineItem } from '..'

import api from 'lib/api'
import { Dayjs } from 'lib/dayjs'

import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { RecordingSnapshot } from '~/types'

import { SnapshotLoader, WithId } from '../../snapshot-loader'

export function BasePreview({
    name,
    description,
}: {
    name: React.ReactNode
    description?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex justify-between items-center">
            <span className="font-medium">{name}</span>
            {description && (
                <span className="text-secondary text-xs line-clamp-1 max-w-2/3 text-right">{description}</span>
            )}
        </div>
    )
}

export abstract class EventLoader<T extends TimelineItem> implements ItemLoader<T> {
    private cache: ItemCache<T>
    private afterCursor: Dayjs
    private previousCursor: Dayjs
    private _hasNext: boolean = true
    private _hasPrevious: boolean = true

    constructor(
        private sessionId: string,
        timestamp: Dayjs
    ) {
        this.afterCursor = timestamp
        this.previousCursor = timestamp
        this.cache = new ItemCache<T>()
    }

    hasPrevious(to: Dayjs): boolean {
        if (this.cache.previous(to)) {
            return true
        }
        return this._hasPrevious
    }

    hasNext(from: Dayjs): boolean {
        if (this.cache.next(from)) {
            return true
        }
        return this._hasNext
    }

    async previous(to: Dayjs, limit: number): Promise<T | null> {
        const item = this.cache.previous(to)
        if (item) {
            return item
        } else if (this._hasPrevious) {
            const query = this.buildQueryTo(this.previousCursor, limit)
            const response = await api.query(query)
            if (response.results.length === 0) {
                this._hasPrevious = false
            }
            const items = response.results.map(this.buildItem)
            if (items.length > 0) {
                this.previousCursor = items[items.length - 1].timestamp
            }
            this.cache.add(items)
            return this.cache.previous(to) ?? null
        }
        return null
    }

    async next(from: Dayjs, limit: number): Promise<T | null> {
        const item = this.cache.next(from)
        if (item) {
            return item
        } else if (this._hasNext) {
            const query = this.buildQueryFrom(this.afterCursor, limit)
            const response = await api.query(query)
            if (response.results.length === 0) {
                this._hasNext = false
            }
            const items = response.results.map(this.buildItem)
            if (items.length > 0) {
                this.afterCursor = items[items.length - 1].timestamp
            }
            this.cache.add(items)
            return this.cache.next(from) ?? null
        }
        return null
    }

    buildQueryFrom(from: Dayjs, limit: number): EventsQuery {
        return {
            kind: NodeKind.EventsQuery,
            select: this.select(),
            where: [`equals($session_id, '${this.sessionId}')`, ...this.where()],
            after: from.toISOString(),
            before: from.add(6, 'hours').toISOString(),
            orderBy: ['timestamp ASC'],
            limit: limit,
        }
    }

    buildQueryTo(to: Dayjs, limit: number): EventsQuery {
        return {
            kind: NodeKind.EventsQuery,
            select: this.select(),
            where: [`equals($session_id, '${this.sessionId}')`, ...this.where()],
            after: to.subtract(6, 'hours').toISOString(),
            before: to.toISOString(),
            orderBy: ['timestamp DESC'],
            limit: limit,
        }
    }

    abstract select(): string[]
    abstract where(): string[]
    abstract buildItem(data: any): T
}

export interface RecordingSnapshotItem extends TimelineItem {
    id: string
    timestamp: Dayjs
    payload: RecordingSnapshot
}

export abstract class SnapshotItemLoader<T extends TimelineItem> implements ItemLoader<T> {
    cache: ItemCache<T>

    constructor(private snapshotLoader: SnapshotLoader) {
        this.cache = new ItemCache<T>()
    }

    hasNext(index: Dayjs): boolean {
        if (this.cache.next(index)) {
            return true
        }
        const sources = this.snapshotLoader.getSourcesForTimeRange(index, index)
        if (!sources) {
            // Sources are not loaded yet
            return true
        }
        if (sources.length === 0) {
            // No sources available for the next time range
            return false
        }
        return true
    }

    async next(index: Dayjs): Promise<T | null> {
        const item = this.cache.next(index)
        if (item) {
            return item
        }
        const snapshots = await this.snapshotLoader.loadSnapshotsForTimeRange(index, index)
        if (!snapshots.length) {
            return null
        }
        this.addSnapshots(snapshots)
        return this.cache.next(index) ?? null
    }

    hasPrevious(index: Dayjs): boolean {
        const sources = this.snapshotLoader.getSourcesForTimeRange(index, index)
        if (!sources) {
            // Sources are not loaded yet
            return true
        }
        if (sources.length === 0) {
            // No sources available for the next time range
            return false
        }
        return true
    }

    async previous(index: Dayjs): Promise<T | null> {
        const item = this.cache.previous(index)
        if (item) {
            return item
        }
        const snapshots = await this.snapshotLoader.loadSnapshotsForTimeRange(index, index)
        if (!snapshots.length) {
            return null
        }
        this.addSnapshots(snapshots)
        return this.cache.next(index) ?? null
    }

    private addSnapshots(snapshots: WithId<RecordingSnapshot>[]): void {
        this.cache.add(snapshots.map(this.fromSnapshot).filter((item) => item !== null) as Array<T>)
    }

    abstract fromSnapshot(snapshot: WithId<RecordingSnapshot>): T | null
}
