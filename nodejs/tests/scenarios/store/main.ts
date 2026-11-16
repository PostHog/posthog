import { startStore } from './server'

// Usage: DATABASE_URL=... SCENARIO_STORE_TOKEN=... PORT=8080 pnpm --dir nodejs exec tsx tests/scenarios/store/main.ts
if (require.main === module) {
    const { DATABASE_URL, SCENARIO_STORE_TOKEN, PORT } = process.env
    if (!DATABASE_URL || !SCENARIO_STORE_TOKEN) {
        process.stderr.write('Set DATABASE_URL and SCENARIO_STORE_TOKEN.\n')
        process.exit(2)
    }
    startStore({ databaseUrl: DATABASE_URL, token: SCENARIO_STORE_TOKEN, port: Number(PORT ?? 8080) }).then(
        ({ url, close }) => {
            process.stdout.write(`The run store listens on ${url}.\n`)
            for (const signal of ['SIGINT', 'SIGTERM'] as const) {
                process.once(signal, () => void close().then(() => process.exit(0)))
            }
        },
        (error: unknown) => {
            process.stderr.write(`The run store did not start: ${String(error)}\n`)
            process.exit(1)
        }
    )
}
