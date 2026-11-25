import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

export const COUNTERS = ['email_sent', 'email_delivered', 'email_bounced', 'email_failed'] as const

export type Counter = (typeof COUNTERS)[number]

export type Counted = Record<Counter, number>

export type CounterQuery = { teams: number[]; from: number }

export interface CounterProbe {
    counted(query: CounterQuery): Promise<Counted>
}

export type ClickHouseAddress = { url: string; database: string }

export const clickhouseOf = (env: NodeJS.ProcessEnv): ClickHouseAddress => ({
    url: `http://${env.CLICKHOUSE_HOST || 'localhost'}:8123`,
    database: env.CLICKHOUSE_DATABASE || 'posthog',
})

const READ_TIMEOUT_MS = 5000

// The aggregator truncates each app metric's timestamp to its hour, so the window opens at the hour the run started.
const COUNTED = `
    SELECT metric_name, toString(sum(count)) AS total
    FROM app_metrics2
    WHERE team_id IN {teams:Array(Int64)}
      AND app_source = 'hog_flow'
      AND metric_name IN {counters:Array(String)}
      AND timestamp >= toStartOfHour(fromUnixTimestamp64Milli({from:Int64}))
    GROUP BY metric_name
    FORMAT JSONEachRow`

export function createCounterProbe({ url, database }: ClickHouseAddress): CounterProbe {
    return {
        async counted({ teams, from }) {
            const params = new URLSearchParams({
                database,
                param_teams: JSON.stringify(teams),
                param_counters: `[${COUNTERS.map((counter) => `'${counter}'`).join(',')}]`,
                param_from: String(from),
            })
            const response = await internalFetch(`${url}/?${params}`, {
                method: 'POST',
                body: COUNTED,
                timeoutMs: READ_TIMEOUT_MS,
            })
            const text = await response.text()
            if (response.status !== 200) {
                throw new Error(`ClickHouse answered the counter read with ${response.status}: ${text.trim()}`)
            }
            const counted = Object.fromEntries(COUNTERS.map((counter) => [counter, 0])) as Counted
            for (const line of text.split('\n').filter(Boolean)) {
                const { metric_name, total } = parseJSON(line) as { metric_name: Counter; total: string }
                counted[metric_name] = Number(total)
            }
            return counted
        },
    }
}
