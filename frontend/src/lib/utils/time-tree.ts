import { RBTree } from 'bintrees'

import { Dayjs } from 'lib/dayjs'

export type TimeTreeComparable = {
    timestamp: Dayjs
    id?: string | number
    category?: string | number
    sortPriority?: number
}

export function compareTimeTreeItems<T extends TimeTreeComparable>(a: T, b: T): number {
    const timestampDiff = a.timestamp.diff(b.timestamp)
    if (timestampDiff !== 0) {
        return timestampDiff
    }

    const sortPriorityDiff = (a.sortPriority ?? 0) - (b.sortPriority ?? 0)
    if (sortPriorityDiff !== 0) {
        return sortPriorityDiff
    }

    const categoryDiff = String(a.category ?? '').localeCompare(String(b.category ?? ''))
    if (categoryDiff !== 0) {
        return categoryDiff
    }

    return String(a.id ?? '').localeCompare(String(b.id ?? ''))
}

// Data structure for fast insert and search operations based on timestamps.
export class TimeTree<T extends TimeTreeComparable> {
    tree: RBTree<T>

    constructor() {
        this.tree = new RBTree(compareTimeTreeItems)
    }

    clear(): void {
        this.tree = new RBTree(compareTimeTreeItems)
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

    // Return the previous item in the tree, or undefined if there is no previous item.
    previous(to: Dayjs): T | undefined {
        const needle = {
            timestamp: to,
        } as T
        const it = this.tree.lowerBound(needle) // first >= x
        if (it.data() === null) {
            // x is greater than all items; predecessor is max (if any)
            const v = this.tree.max()
            return v === null ? undefined : v
        }
        const prev = it.prev()
        return prev === null ? undefined : prev
    }

    // Return the next item in the tree, or undefined if there is no next item.
    next(from: Dayjs): T | undefined {
        const needle = {
            timestamp: from,
        } as T
        const it = this.tree.upperBound(needle) // first > x
        const v = it.data()
        return v === null ? undefined : v // bintrees returns null at end
    }
}
