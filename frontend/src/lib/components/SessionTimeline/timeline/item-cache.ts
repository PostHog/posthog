import { TimelineItem } from '.'

import { Dayjs } from 'lib/dayjs'

export class ItemCache<T extends TimelineItem> {
    orderedIds: string[]
    queue: Record<string, T>

    constructor() {
        this.queue = {}
        this.orderedIds = []
    }

    private sort(): void {
        this.orderedIds = Object.keys(this.queue).sort((a, b) => this.queue[a].timestamp.diff(this.queue[b].timestamp))
    }

    clear(): void {
        this.queue = {}
        this.orderedIds = []
    }

    getAll(): T[] {
        return this.orderedIds.map((id) => this.queue[id])
    }

    add(items: T[]): void {
        for (const item of items) {
            this.queue[item.id] = item
        }
        this.sort()
    }

    next(from: Dayjs): T | undefined {
        for (const id of this.orderedIds) {
            const item = this.queue[id]
            if (item.timestamp.isAfter(from)) {
                return item
            }
        }
    }

    previous(to: Dayjs): T | undefined {
        for (let i = this.orderedIds.length - 1; i >= 0; i--) {
            const id = this.orderedIds[i]
            const item = this.queue[id]
            if (item.timestamp.isBefore(to)) {
                return item
            }
        }
    }
}
