import { randomInt } from 'crypto'

import { internalFetch } from '~/common/utils/request'

import { createCounterProbe } from './counter-probe'

const CLICKHOUSE = {
    url: `http://${process.env.CLICKHOUSE_HOST ?? 'localhost'}:8123`,
    database: process.env.CLICKHOUSE_DATABASE ?? 'posthog_test',
}

type Row = { team: number; source?: string; metric: string; count: number; at: string }

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
        const from = Date.parse('2026-01-05T10:20:00.000Z')
        const hour = '2026-01-05 10:00:00'
        await insert([
            { team: ours, metric: 'email_sent', count: 3, at: hour },
            { team: ours, metric: 'email_sent', count: 2, at: '2026-01-05 11:00:00' },
            { team: alsoOurs, metric: 'email_sent', count: 1, at: hour },
            { team: ours, metric: 'email_bounced', count: 1, at: hour },
            { team: ours, metric: 'email_failed', count: 4, at: hour },
            { team: ours, metric: 'email_sent', count: 7, at: '2026-01-05 09:00:00' },
            { team: ours, source: 'hog_flow_version', metric: 'email_sent', count: 5, at: hour },
            { team: ours, metric: 'email_untracked', count: 5, at: hour },
            { team: theirs, metric: 'email_sent', count: 9, at: hour },
        ])

        const counted = await createCounterProbe(CLICKHOUSE).counted({ teams: [ours, alsoOurs], from })

        expect(counted).toEqual({ email_sent: 6, email_delivered: 0, email_bounced: 1, email_failed: 4 })
    })
})
