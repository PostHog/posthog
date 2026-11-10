import { Pool } from 'pg'

import { waitForExpect } from '../../../../tests/helpers/expectations'
import { CyclotronJobQueueKind } from '../../types'
import { CyclotronJobQueuePostgresV2 } from './job-queue-postgres-v2'

const APPLICATION_NAME = 'job-queue-postgres-v2-shared-stop'
const DB_URL = `postgres://posthog:posthog@localhost:5432/test_cyclotron_node?application_name=${APPLICATION_NAME}`

describe('CyclotronJobQueuePostgresV2 on Postgres', () => {
    let assertPool: Pool

    beforeAll(() => {
        assertPool = new Pool({ connectionString: 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node' })
    })

    afterAll(async () => {
        await assertPool.end()
    })

    async function openSessions(): Promise<number> {
        const { rows } = await assertPool.query<{ n: number }>(
            'SELECT COUNT(*)::int AS n FROM pg_stat_activity WHERE application_name = $1',
            [APPLICATION_NAME]
        )
        return rows[0].n
    }

    it('lets two consumers that share the queue stop it at the same time', async () => {
        const queue = new CyclotronJobQueuePostgresV2(10, {
            CYCLOTRON_NODE_DATABASE_URL: DB_URL,
            CYCLOTRON_SHARD_DEPTH_LIMIT: 1_000_000,
            CDP_CYCLOTRON_BATCH_DELAY_MS: 20,
            CDP_CYCLOTRON_BATCH_DELAY_MAX_MS: 0,
            CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE: 1000,
            CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES: false,
            CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '',
        })
        await queue.startAsConsumer('job-queue-shared-stop' as CyclotronJobQueueKind, () =>
            Promise.resolve({ backgroundTask: Promise.resolve() })
        )
        await waitForExpect(async () => expect(await openSessions()).toBeGreaterThan(0))

        const stopLikeAWorkerConsumer = async (): Promise<void> => {
            await queue.stopConsumer()
            await queue.stopProducer()
        }
        await Promise.all([stopLikeAWorkerConsumer(), stopLikeAWorkerConsumer()])

        await waitForExpect(async () => expect(await openSessions()).toBe(0))
    })
})
