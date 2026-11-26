import { randomInt } from 'crypto'

import { internalFetch } from '~/common/utils/request'

import { createCounterProbe } from './counter-probe'

const CLICKHOUSE = {
    url: `http://${process.env.CLICKHOUSE_HOST ?? 'localhost'}:8123`,
    database: process.env.CLICKHOUSE_DATABASE ?? 'posthog_test',
}

type Row = { team: number; source?: string; metric: string; count: number; at: string }

async function run(statement: string, database = 'default'): Promise<void> {
    const response = await internalFetch(`${CLICKHOUSE.url}/?database=${database}`, { method: 'POST', body: statement })
    if (response.status !== 200) {
        throw new Error(`${statement} failed with ${response.status}: ${await response.text()}`)
    }
}

async function insert(rows: Row[]): Promise<void> {
    const body = rows
        .map(({ team, source = 'hog_flow', metric, count, at }) =>
            JSON.stringify({
                team_id: team,
                timestamp: at,
                app_source: source,
                app_source_id: 'flow',
                instance_id: 'email',
                metric_kind: 'email',
                metric_name: metric,
                count,
            })
        )
        .join('\n')
    const query = encodeURIComponent('INSERT INTO sharded_app_metrics2 FORMAT JSONEachRow')
    const response = await internalFetch(`${CLICKHOUSE.url}/?database=${CLICKHOUSE.database}&query=${query}`, {
        method: 'POST',
        body,
    })
    if (response.status !== 200) {
        throw new Error(`insert failed with ${response.status}: ${await response.text()}`)
    }
}

describe('counter probe', () => {
    it("sums each email counter of the run's teams from the hour the run started", async () => {
        const [ours, alsoOurs, theirs] = [randomInt(1e9, 2e9), randomInt(1e9, 2e9), randomInt(1e9, 2e9)]
        const HOUR_MS = 3_600_000
        const runHour = Math.floor(Date.now() / HOUR_MS) * HOUR_MS - 2 * HOUR_MS
        const from = runHour + 20 * 60_000
        const hourAt = (offset: number): string =>
            new Date(runHour + offset * HOUR_MS).toISOString().slice(0, 19).replace('T', ' ')
        const hour = hourAt(0)
        await insert([
            { team: ours, metric: 'email_sent', count: 3, at: hour },
            { team: ours, metric: 'email_sent', count: 2, at: hourAt(1) },
            { team: alsoOurs, metric: 'email_sent', count: 1, at: hour },
            { team: ours, metric: 'email_bounced', count: 1, at: hour },
            { team: ours, metric: 'email_failed', count: 4, at: hour },
            { team: ours, metric: 'email_sent', count: 7, at: hourAt(-1) },
            { team: ours, source: 'hog_flow_version', metric: 'email_sent', count: 5, at: hour },
            { team: ours, metric: 'email_untracked', count: 5, at: hour },
            { team: theirs, metric: 'email_sent', count: 9, at: hour },
        ])

        const counted = await createCounterProbe(CLICKHOUSE).counted({ teams: [ours, alsoOurs], from })

        expect(counted).toEqual({ email_sent: 6, email_delivered: 0, email_failed: 4 })
    })

    it.each<[string, [string, string][], number]>([
        ['one Kafka view writes into app_metrics2', [['kafka_app_metrics2', 'writable_app_metrics2']], 1],
        [
            'two Kafka views write into app_metrics2',
            [
                ['kafka_app_metrics2', 'writable_app_metrics2'],
                ['kafka_app_metrics2_ws', 'writable_app_metrics2'],
            ],
            2,
        ],
        [
            'a second Kafka view writes straight into the sharded table',
            [
                ['kafka_app_metrics2', 'writable_app_metrics2'],
                ['kafka_app_metrics2', 'sharded_app_metrics2'],
            ],
            2,
        ],
        [
            'a second Kafka view writes into the distributed table',
            [
                ['kafka_app_metrics2', 'writable_app_metrics2'],
                ['kafka_app_metrics2_ws', 'app_metrics2'],
            ],
            2,
        ],
        [
            'a second Kafka view writes elsewhere',
            [
                ['kafka_app_metrics2', 'writable_app_metrics2'],
                ['kafka_app_metrics2_ws', 'elsewhere'],
            ],
            1,
        ],
        [
            'a second view reads a table that is not Kafka',
            [
                ['kafka_app_metrics2', 'writable_app_metrics2'],
                ['kafka_app_metrics2_copy', 'writable_app_metrics2'],
            ],
            1,
        ],
    ])(
        'counts the Kafka views that feed app_metrics2 when %s',
        async (_story, views, expected) => {
            const database = `counter_probe_${randomInt(1e9, 2e9)}`
            try {
                await run(`CREATE DATABASE ${database}`)
                for (const source of ['kafka_app_metrics2', 'kafka_app_metrics2_ws']) {
                    await run(
                        `CREATE TABLE ${source} (count Int64) ENGINE = Kafka SETTINGS kafka_broker_list = '127.0.0.1:1', kafka_topic_list = '${database}', kafka_group_name = '${database}_${source}', kafka_format = 'JSONEachRow'`,
                        database
                    )
                }
                for (const table of [
                    'kafka_app_metrics2_copy',
                    'app_metrics2',
                    'writable_app_metrics2',
                    'sharded_app_metrics2',
                    'elsewhere',
                ]) {
                    await run(`CREATE TABLE ${table} (count Int64) ENGINE = Null`, database)
                }
                for (const [i, [source, target]] of views.entries()) {
                    await run(
                        `CREATE MATERIALIZED VIEW view_${i} TO ${target} AS SELECT count FROM ${source}`,
                        database
                    )
                }

                expect(await createCounterProbe({ ...CLICKHOUSE, database }).consumers()).toBe(expected)
            } finally {
                await run(`DROP DATABASE IF EXISTS ${database} SYNC`)
            }
        },
        30_000
    )
})
