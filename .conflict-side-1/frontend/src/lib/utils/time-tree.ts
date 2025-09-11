import { RBTree } from 'bintrees'

import { Dayjs } from 'lib/dayjs'

// Data structure for fast insert and search operations based on timestamps.
export class TimeTree<T extends { timestamp: Dayjs }> {
    tree: RBTree<T>

    constructor() {
        this.tree = new RBTree((a, b) => a.timestamp.diff(b.timestamp))
    }

    clear(): void {
        this.tree = new RBTree((a, b) => a.timestamp.diff(b.timestamp))
    }

    getAll(): T[] {
        const items: T[] = []
        this.tree.each((item) => {
            items.push(item)
        })
        return items
    }

    add(items: T[]): void {
        for (const item of items) {
            this.tree.insert(item)
        }
    }

    next(from: Dayjs): T | undefined {
        const nextIter = this.tree.upperBound({
            timestamp: from,
        } as T)
        return nextIter.next() ?? undefined
    }

    previous(to: Dayjs): T | undefined {
        const prevIter = this.tree.lowerBound({
            timestamp: to,
        } as T)
        return prevIter.prev() ?? undefined
    }
}
