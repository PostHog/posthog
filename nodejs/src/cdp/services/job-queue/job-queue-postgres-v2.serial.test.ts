import { Pool } from 'pg'

import { waitForExpect } from '../../../../tests/helpers/expectations'
import { createExampleInvocation } from '../../_tests/fixtures'
import { CyclotronJobInvocation, CyclotronJobQueueKind } from '../../types'
import { CyclotronJobQueuePostgresV2 } from './job-queue-postgres-v2'

const APPLICATION_NAME = 'job-queue-postgres-v2-shared-stop'
const DB_URL = `postgres://posthog:posthog@localhost:5432/test_cyclotron_node?application_name=${APPLICATION_NAME}`
const QUEUE = 'job-queue-shared-stop' as CyclotronJobQueueKind
const FOLLOW_UP_QUEUE = 'job-queue-shared-stop-follow-up' as CyclotronJobQueueKind

describe('CyclotronJobQueuePostgresV2 on Postgres', () => {
    let assertPool: Pool

    beforeAll(() => {
        assertPool = new Pool({ connectionString: 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node' })
    })

    afterEach(async () => {
        await assertPool.query('DELETE FROM cyclotron_jobs WHERE queue_name = ANY($1)', [[QUEUE, FOLLOW_UP_QUEUE]])
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

    it('lets two consumers that share the queue stop it while a batch is still enqueuing jobs', async () => {
        const queue = new CyclotronJobQueuePostgresV2(10, {
            CYCLOTRON_NODE_DATABASE_URL: DB_URL,
            CYCLOTRON_SHARD_DEPTH_LIMIT: 1_000_000,
            CDP_CYCLOTRON_BATCH_DELAY_MS: 20,
            CDP_CYCLOTRON_BATCH_DELAY_MAX_MS: 0,
            CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE: 1000,
            CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES: false,
            CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '',
        })
        await queue.startAsProducer()
        await queue.queueInvocations([createExampleInvocation({}, {}, QUEUE)])

        const followUp = createExampleInvocation({}, {}, FOLLOW_UP_QUEUE)
        let batchStarted!: () => void
        const batchInFlight = new Promise<void>((resolve) => (batchStarted = resolve))
        let releaseBatch!: () => void
        const batchReleased = new Promise<void>((resolve) => (releaseBatch = resolve))
        let followUpError: unknown

        await queue.startAsConsumer(QUEUE, async (invocations: CyclotronJobInvocation[]) => {
            if (invocations.length > 0) {
                batchStarted()
                await batchReleased
                await queue.queueInvocations([followUp]).catch((error) => (followUpError = error))
            }
            return { backgroundTask: Promise.resolve() }
        })
        await batchInFlight

        const stopLikeAWorkerConsumer = async (): Promise<void> => {
            await queue.stopConsumer()
            await queue.stopProducer()
        }
        const stops = Promise.all([stopLikeAWorkerConsumer(), stopLikeAWorkerConsumer()])
        await new Promise((resolve) => setImmediate(resolve))
        releaseBatch()
        await stops

        expect(followUpError).toBeUndefined()
        const { rows } = await assertPool.query('SELECT id FROM cyclotron_jobs WHERE id = $1', [followUp.id])
        expect(rows).toHaveLength(1)
        await waitForExpect(async () => expect(await openSessions()).toBe(0))
    })
})
