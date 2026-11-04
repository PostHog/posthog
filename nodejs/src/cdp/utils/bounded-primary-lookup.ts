import { PostgresRouter, PostgresUse, TransactionClient } from '~/common/utils/db/postgres'

import { DeadlineSlots } from './deadline-slots'

type BoundedPrimaryLookupOptions = {
    name: string
    timeoutMs: number
    maxOpen: number
}

// A read on the primary that a send waits for. A stalled one fails the check instead of holding up every other
// send in the worker's batch. The deadline counts the wait for a pooled connection too, and the statement timeout
// also stops the query on the server. A lookup past its deadline still waits in the common pool until it gets a
// connection, so at most `maxOpen` are open at once. A lookup waiting for a slot holds nothing and fails at its deadline.
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
            const value = await this.postgres.transaction(PostgresUse.COMMON_WRITE, tag, async (tx) => {
                // Nobody waits for a lookup that got its connection after its deadline, so it runs no query.
                if (timedOut) {
                    throw new Error(`The ${name} lookup was abandoned at its deadline`)
                }
                await this.postgres.query(tx, `SET LOCAL statement_timeout = ${timeoutMs}`, undefined, tag)
                return await read(tx)
            })
            result = { value }
        })
        // A lookup that loses the race can still fail later, after nobody waits for it.
        lookup.catch(() => undefined)
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
