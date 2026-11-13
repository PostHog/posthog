import { performance } from 'perf_hooks'
import { Client } from 'pg'

import { withPostgres } from '../environment/stack'

export type WriterSample = {
    at: number
    monoMs: number
    ok: boolean
    latencyMs: number
    inRecovery?: boolean
    sqlstate?: string
}

export interface WriterProbe {
    sample(): Promise<WriterSample>
    end(): Promise<void>
}

const TIMEOUT_MS = 2000
const SQLSTATE = /^[0-9A-Z]{5}$/

function sqlstateOf(error: unknown): { sqlstate?: string } {
    const code = (error as { code?: unknown } | undefined)?.code
    return typeof code === 'string' && SQLSTATE.test(code) ? { sqlstate: code } : {}
}

export async function createWriterProbe(
    cyclotronUrl: string,
    applicationName = 'scenario-writer-probe'
): Promise<WriterProbe> {
    await withPostgres(
        (client) =>
            client.query(
                'CREATE TABLE IF NOT EXISTS scenario_writer_probe (id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now())'
            ),
        cyclotronUrl
    )
    let open: Client | undefined
    const drop = async (): Promise<void> => {
        const client = open
        open = undefined
        await client?.end().catch(() => undefined)
    }
    const connected = async (): Promise<Client> => {
        if (open === undefined) {
            const client = new Client({
                connectionString: cyclotronUrl,
                application_name: applicationName,
                connectionTimeoutMillis: TIMEOUT_MS,
                statement_timeout: TIMEOUT_MS,
                query_timeout: TIMEOUT_MS,
            })
            client.on('error', () => undefined)
            open = client
            await client.connect()
        }
        return open
    }
    return {
        async sample() {
            const at = Date.now()
            const monoMs = performance.now()
            try {
                const client = await connected()
                const { rows } = await client.query<{ in_recovery: boolean }>(
                    `WITH probe AS (INSERT INTO scenario_writer_probe DEFAULT VALUES RETURNING id)
                     SELECT pg_is_in_recovery() AS in_recovery FROM probe`
                )
                return { at, monoMs, ok: true, latencyMs: performance.now() - monoMs, inRecovery: rows[0].in_recovery }
            } catch (error) {
                await drop()
                return { at, monoMs, ok: false, latencyMs: performance.now() - monoMs, ...sqlstateOf(error) }
            }
        },
        end: drop,
    }
}
