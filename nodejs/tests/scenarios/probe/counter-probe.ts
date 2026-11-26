import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

export const COUNTERS = ['email_sent', 'email_delivered', 'email_failed'] as const

export type Counter = (typeof COUNTERS)[number]

export type Counted = Record<Counter, number>

export type CounterQuery = { teams: number[]; from: number }

export interface CounterProbe {
    counted(query: CounterQuery): Promise<Counted>
    consumers(): Promise<number>
}

export type ClickHouseAddress = { url: string; database: string }

export const clickhouseOf = (env: NodeJS.ProcessEnv): ClickHouseAddress => ({
    url: `http://${env.CLICKHOUSE_HOST || 'localhost'}:8123`,
    database: env.CLICKHOUSE_DATABASE || 'posthog',
})

const READ_TIMEOUT_MS = 5000
const MAX_RESPONSE_BYTES = 64 * 1024
const MAX_ERROR_CHARS = 300

const COUNTED = `
    SELECT metric_name, toString(sum(count)) AS total
    FROM app_metrics2
    WHERE team_id IN {teams:Array(Int64)}
      AND app_source = 'hog_flow'
      AND metric_name IN {counters:Array(String)}
      AND timestamp >= toStartOfHour(fromUnixTimestamp64Milli({from:Int64}))
    GROUP BY metric_name
    FORMAT JSONEachRow`

const CONSUMERS = `
    WITH (
        SELECT groupArray(name) FROM system.tables WHERE database = {database:String} AND engine = 'Kafka'
    ) AS kafka_tables
    SELECT count() AS consumers
    FROM system.tables
    WHERE database = {database:String}
      AND engine = 'MaterializedView'
      AND arrayExists(
          (source) -> match(create_table_query, concat(' FROM ', {database:String}, '[.]', source, '([[:space:]]|$)')),
          kafka_tables
      )
      AND match(create_table_query, concat(' TO ', {database:String}, '[.](writable_|sharded_)?app_metrics2[[:space:]]'))
    FORMAT JSONEachRow`

export function createCounterProbe({ url, database }: ClickHouseAddress): CounterProbe {
    const read = async (query: string, params: Record<string, string>, what: string): Promise<string> => {
        const response = await internalFetch(`${url}/?${new URLSearchParams({ database, ...params })}`, {
            method: 'POST',
            body: query,
            timeoutMs: READ_TIMEOUT_MS,
            maxResponseBytes: MAX_RESPONSE_BYTES,
        })
        const text = await response.text()
        if (response.status !== 200) {
            throw new Error(
                `ClickHouse answered the ${what} read with ${response.status}: ${text.trim().slice(0, MAX_ERROR_CHARS)}`
            )
        }
        return text
    }
    return {
        async consumers() {
            const text = await read(CONSUMERS, { param_database: database }, 'consumer')
            return Number((parseJSON(text) as { consumers: string | number }).consumers)
        },
        async counted({ teams, from }) {
            const params = {
                param_teams: JSON.stringify(teams),
                param_counters: `[${COUNTERS.map((counter) => `'${counter}'`).join(',')}]`,
                param_from: String(from),
            }
            const text = await read(COUNTED, params, 'counter')
            const counted = Object.fromEntries(COUNTERS.map((counter) => [counter, 0])) as Counted
            for (const line of text.split('\n').filter(Boolean)) {
                const { metric_name, total } = parseJSON(line) as { metric_name: Counter; total: string }
                counted[metric_name] = Number(total)
            }
            return counted
        },
    }
}
