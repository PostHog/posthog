import { startStore } from './server'

if (require.main === module) {
    const { DATABASE_URL, SCENARIO_STORE_TOKEN, PORT, HOST } = process.env
    if (!DATABASE_URL) {
        process.stderr.write('Set DATABASE_URL.\n')
        process.exit(2)
    }
    startStore({
        databaseUrl: DATABASE_URL,
        token: SCENARIO_STORE_TOKEN ?? '',
        port: Number(PORT ?? 8080),
        host: HOST,
    }).then(
        ({ url, close }) => {
            process.stdout.write(`The run store listens on ${url}.\n`)
            for (const signal of ['SIGINT', 'SIGTERM'] as const) {
                process.once(signal, () => {
                    close().then(
                        () => process.exit(0),
                        (error: unknown) => {
                            process.stderr.write(`The run store did not close cleanly: ${String(error)}\n`)
                            process.exit(1)
                        }
                    )
                })
            }
        },
        (error: unknown) => {
            process.stderr.write(`The run store did not start: ${String(error)}\n`)
            process.exit(1)
        }
    )
}
