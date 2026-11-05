import { PostgresRouter, TransactionClient } from '~/common/utils/db/postgres'

import { DeadlineSlots } from './deadline-slots'
import { runTransactionBeforeDeadline } from './deadline-transaction'

type BoundedPrimaryLookupOptions = {
    name: string
    timeoutMs: number
    maxOpen: number
}

export class BoundedPrimaryLookup {
    private slots: DeadlineSlots

    constructor(
        private postgres: PostgresRouter,
        private readonly options: BoundedPrimaryLookupOptions
    ) {
        this.slots = new DeadlineSlots(options.maxOpen)
    }

    public async run<Result>(tag: string, read: (tx: TransactionClient) => Promise<Result>): Promise<Result> {
        const { name, timeoutMs } = this.options
        let timedOut = false
        let timer: NodeJS.Timeout | undefined
        const deadline = new Promise<void>((resolve) => {
            timer = setTimeout(() => {
                timedOut = true
                resolve()
            }, timeoutMs)
        })
        let result: { value: Result } | undefined
        const lookup = this.slots.run(deadline, async () => {
            const value = await runTransactionBeforeDeadline(
                this.postgres,
                tag,
                { reached: deadline, hasPassed: () => timedOut },
                timeoutMs,
                read
            )
            result = { value }
        })
        const ignoreFailureAfterDeadline = (): undefined => undefined
        lookup.catch(ignoreFailureAfterDeadline)
        try {
            await Promise.race([lookup, deadline])
        } finally {
            clearTimeout(timer)
        }
        if (!result) {
            throw new Error(`The ${name} lookup timed out`)
        }
        return result.value
    }
}
