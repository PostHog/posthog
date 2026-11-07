import { PostgresRouter, TransactionClient } from '~/common/utils/db/postgres'

import { runTransactionBeforeDeadline } from './deadline-transaction'
import { Semaphore } from './sempahore'

type BoundedPrimaryLookupOptions = {
    name: string
    timeoutMs: number
    maxOpen: number
}

export class BoundedPrimaryLookup {
    private slots: Semaphore

    constructor(
        private postgres: PostgresRouter,
        private readonly options: BoundedPrimaryLookupOptions
    ) {
        this.slots = new Semaphore(options.maxOpen)
    }

    public async run<Result>(
        tag: string,
        read: (tx: TransactionClient) => Promise<Result>,
        { timeoutMs = this.options.timeoutMs }: { timeoutMs?: number } = {}
    ): Promise<Result> {
        const { name } = this.options
        let timedOut = false
        let timer: NodeJS.Timeout | undefined
        const deadline = new Promise<void>((resolve) => {
            timer = setTimeout(() => {
                timedOut = true
                resolve()
            }, timeoutMs)
        })
        const lookup = this.slots.run(
            () =>
                runTransactionBeforeDeadline(
                    this.postgres,
                    tag,
                    { reached: deadline, hasPassed: () => timedOut },
                    timeoutMs,
                    read
                ),
            deadline
        )
        try {
            return await Promise.race([lookup, deadline.then(() => Promise.reject(new Error('timed out')))])
        } catch (error) {
            if (timedOut) {
                throw new Error(`The ${name} lookup timed out`)
            }
            throw error
        } finally {
            clearTimeout(timer)
        }
    }
}
