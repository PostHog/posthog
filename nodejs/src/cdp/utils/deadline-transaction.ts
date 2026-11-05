import { PostgresRouter, PostgresUse, TransactionClient, handlePostgresError } from '~/common/utils/db/postgres'

export type Deadline = {
    readonly reached: Promise<void>
    readonly hasPassed: () => boolean
}

// Takes the pooled client itself, so a client that arrives after the deadline sends no SQL, BEGIN included,
// and a client still busy at the deadline is destroyed. It settles only after the client is released or destroyed.
export async function runTransactionBeforeDeadline<Result>(
    postgres: PostgresRouter,
    tag: string,
    deadline: Deadline,
    statementTimeoutMs: number,
    read: (tx: TransactionClient) => Promise<Result>
): Promise<Result> {
    let client: Awaited<ReturnType<PostgresRouter['connect']>>
    try {
        client = await postgres.connect(PostgresUse.COMMON_WRITE)
    } catch (error) {
        handlePostgresError(error as Error, PostgresUse.COMMON_WRITE)
        throw error
    }
    if (deadline.hasPassed()) {
        client.release()
        throw new Error(`The ${tag} lookup got its connection after its deadline`)
    }
    // pg removes the pool's error listener from a checked-out client, so a lost connection would crash the process.
    let lostConnection: Error | undefined
    const onClientError = (error: Error): void => {
        lostConnection = error
    }
    client.on('error', onClientError)

    const tx = new TransactionClient(PostgresUse.COMMON_WRITE, client)
    const statements = (async (): Promise<Result> => {
        await client.query('BEGIN')
        await postgres.query(tx, `SET LOCAL statement_timeout = ${statementTimeoutMs}`, undefined, tag)
        const result = await read(tx)
        await client.query('COMMIT')
        return result
    })()
    const expired = deadline.reached.then(() => Promise.reject(new Error(`The ${tag} lookup passed its deadline`)))
    statements.catch(() => undefined)
    expired.catch(() => undefined)

    try {
        const result = await Promise.race([statements, expired])
        client.removeListener('error', onClientError)
        client.release(lostConnection)
        return result
    } catch (error) {
        // The connection can still run a statement or hold an open transaction, so the pool must not reuse it.
        client.release(lostConnection ?? (error as Error))
        handlePostgresError(error as Error, PostgresUse.COMMON_WRITE)
        throw error
    }
}
