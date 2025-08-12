import { Client } from 'pg'
import { defaultConfig } from '../config/config'

function toAdminDbUrl(urlStr: string): string {
    const u = new URL(urlStr)
    // connect to the built-in 'postgres' DB for ALTER SYSTEM
    u.pathname = '/postgres'
    return u.toString()
}

async function getMaxPreparedTransactions(client: Client): Promise<number> {
    const { rows } = await client.query(`SHOW max_prepared_transactions`)
    const val = parseInt(rows[0].max_prepared_transactions, 10)
    return Number.isFinite(val) ? val : 0
}

async function main() {
    const urls = [
        process.env.DATABASE_URL || defaultConfig.DATABASE_URL,
        process.env.PERSONS_DATABASE_URL || defaultConfig.PERSONS_DATABASE_URL,
        process.env.PERSONS_MIGRATION_DATABASE_URL || defaultConfig.PERSONS_MIGRATION_DATABASE_URL,
    ].filter(Boolean) as string[]

    // Deduplicate by origin (host:port) so we hit each server once
    const servers = Array.from(
        new Map(
            urls.map((u) => {
                const parsed = new URL(u)
                const key = `${parsed.protocol}//${parsed.username}:${parsed.password}@${parsed.host}`
                return [key, u]
            })
        ).values()
    )

    for (const url of servers) {
        const adminUrl = toAdminDbUrl(url)
        const client = new Client({ connectionString: adminUrl })
        await client.connect()
        try {
            const current = await getMaxPreparedTransactions(client)
            if (current > 0) {
                continue
            }

            try {
                await client.query(`ALTER SYSTEM SET max_prepared_transactions = 10`)
                await client.query(`SELECT pg_reload_conf()`)
                // eslint-disable-next-line no-console
                console.warn(
                    `[enable-prepared-transactions] Set max_prepared_transactions=10 on ${adminUrl}. Restart PostgreSQL for it to take effect.`
                )
            } catch (e) {
                // eslint-disable-next-line no-console
                console.warn(
                    `[enable-prepared-transactions] Could not set max_prepared_transactions on ${adminUrl} (requires superuser). Please set it to > 0 and restart PostgreSQL.`
                )
            }
        } finally {
            await client.end()
        }
    }
}

main().catch((err) => {
    // eslint-disable-next-line no-console
    console.error(err)
    process.exit(1)
})


