import { ItemLoader, TimelineItem } from '..'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { TimeTree } from 'lib/utils/time-tree'

import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { HogQLQueryString, hogql } from '~/queries/utils'

export function BasePreview({
    name,
    description,
    descriptionTitle,
}: {
    name: React.ReactNode
    descriptionTitle?: string
    description?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex justify-between items-center">
            <span className="font-medium">{name}</span>
            {description && (
                <span className="text-secondary text-xs line-clamp-1 max-w-2/3 text-right" title={descriptionTitle}>
                    {description}
                </span>
            )}
        </div>
    )
}

export abstract class QueryLoader<T extends TimelineItem> implements ItemLoader<T> {
    private cache: TimeTree<T>
    private afterCursor: Dayjs
    private previousCursor: Dayjs
    private _hasNext: boolean = true
    private _hasPrevious: boolean = true

    constructor(timestamp: Dayjs) {
        this.afterCursor = timestamp
        this.previousCursor = timestamp
        this.cache = new TimeTree<T>()
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
            const items = await this.queryTo(this.previousCursor, limit)
            if (items.length === 0) {
                this._hasPrevious = false
            } else if (items.length > 0) {
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
            const items = await this.queryFrom(this.afterCursor, limit)
            if (items.length === 0) {
                this._hasNext = false
            } else if (items.length > 0) {
                this.afterCursor = items[items.length - 1].timestamp
            }
            this.cache.add(items)
            return this.cache.next(from) ?? null
        }
        return null
    }

    abstract queryFrom(from: Dayjs, limit: number): Promise<T[]>
    abstract queryTo(to: Dayjs, limit: number): Promise<T[]>
    abstract buildItem(data: any): T
}

export abstract class EventLoader<T extends TimelineItem> extends QueryLoader<T> implements ItemLoader<T> {
    constructor(
        private sessionId: string,
        timestamp: Dayjs
    ) {
        super(timestamp)
    }

    async queryFrom(from: Dayjs, limit: number): Promise<T[]> {
        const query = this.buildQueryFrom(from, limit)
        const response = await api.query(query)
        return response.results.map(this.buildItem)
    }

    async queryTo(to: Dayjs, limit: number): Promise<T[]> {
        const query = this.buildQueryTo(to, limit)
        const response = await api.query(query)
        return response.results.map(this.buildItem)
    }

    private buildQuery(limit: number): Partial<EventsQuery> {
        return {
            kind: NodeKind.EventsQuery,
            select: this.select(),
            where: [`equals($session_id, '${this.sessionId}')`, ...this.where()],
            limit: limit,
        }
    }

    buildQueryFrom(from: Dayjs, limit: number): EventsQuery {
        return {
            ...this.buildQuery(limit),
            after: from.toISOString(),
            before: from.add(6, 'hours').toISOString(),
            orderBy: ['timestamp ASC'],
        } as EventsQuery
    }

    buildQueryTo(to: Dayjs, limit: number): EventsQuery {
        return {
            ...this.buildQuery(limit),
            after: to.subtract(6, 'hours').toISOString(),
            before: to.toISOString(),
            orderBy: ['timestamp DESC'],
        } as EventsQuery
    }

    abstract select(): string[]
    abstract where(): string[]
    abstract buildItem(data: any): T
}

export abstract class LogEntryLoader<T extends TimelineItem> extends QueryLoader<T> implements ItemLoader<T> {
    async queryFrom(from: Dayjs, limit: number): Promise<T[]> {
        const query = this.buildQueryFrom(from, limit)
        const response = await api.queryHogQL(query)
        return response.results.map((row) =>
            this.buildItem({
                timestamp: dayjs.utc(row[0]),
                level: row[1],
                message: row[2],
            })
        )
    }

    async queryTo(to: Dayjs, limit: number): Promise<T[]> {
        const query = this.buildQueryTo(to, limit)
        const response = await api.queryHogQL(query)
        return response.results.map((row) =>
            this.buildItem({
                timestamp: dayjs.utc(row[0]),
                level: row[1],
                message: row[2],
            })
        )
    }

    buildQueryFrom(from: Dayjs, limit: number): HogQLQueryString {
        return hogql`SELECT timestamp, level, message FROM log_entries WHERE log_source = ${this.logSource()} AND log_source_id = ${this.logSourceId()} AND timestamp >= ${from} and timestamp <= ${from.add(6, 'hours')} ORDER BY timestamp ASC LIMIT ${limit}`
    }

    buildQueryTo(to: Dayjs, limit: number): HogQLQueryString {
        return hogql`SELECT timestamp, level, message FROM log_entries WHERE log_source = ${this.logSource()} AND log_source_id = ${this.logSourceId()} AND timestamp <= ${to} and timestamp >= ${to.subtract(6, 'hours')} ORDER BY timestamp DESC LIMIT ${limit}`
    }

    abstract logSource(): string
    abstract logSourceId(): string
    abstract buildItem(item: { timestamp: Dayjs; level: 'info' | 'warn' | 'error'; message: string }): T
}
