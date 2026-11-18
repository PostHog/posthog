type PendingGroup<T> = {
    items: T[]
    batches: number
    timer: NodeJS.Timeout
    done: Promise<void>
    resolve: () => void
    reject: (error: unknown) => void
}

// Each batch settles only when its group is processed, so a consumer that commits after a batch's
// background task keeps at-least-once. The consumer stops fetching at its limit of unsettled tasks,
// so `maxBatches` above that limit would make it wait out the window with nothing to add.
export class BatchCoalescer<T> {
    private pending: PendingGroup<T> | null = null

    constructor(
        private readonly process: (items: T[]) => Promise<void>,
        private readonly windowMs: number,
        private readonly maxBatches: number
    ) {}

    add(items: T[]): Promise<void> {
        if (!(this.windowMs > 0 && this.maxBatches > 1)) {
            return this.run(items)
        }
        if (!this.pending) {
            if (items.length === 0) {
                return Promise.resolve()
            }
            this.pending = this.startGroup()
        }
        // The consumer commits in order, so an empty batch waits for the group anyway and takes a slot.
        const group = this.pending
        group.items.push(...items)
        group.batches++
        if (group.batches >= this.maxBatches) {
            this.flush()
        }
        return group.done
    }

    flush(): void {
        const group = this.pending
        if (!group) {
            return
        }
        this.pending = null
        clearTimeout(group.timer)
        this.run(group.items).then(group.resolve, group.reject)
    }

    private startGroup(): PendingGroup<T> {
        let resolve!: () => void
        let reject!: (error: unknown) => void
        const done = new Promise<void>((res, rej) => {
            resolve = res
            reject = rej
        })
        const timer = setTimeout(() => this.flush(), this.windowMs)
        return { items: [], batches: 0, timer, done, resolve, reject }
    }

    private run(items: T[]): Promise<void> {
        return Promise.resolve().then(() => this.process(items))
    }
}
