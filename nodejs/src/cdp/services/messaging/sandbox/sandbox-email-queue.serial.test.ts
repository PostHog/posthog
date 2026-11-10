import { Pool } from 'pg'
import { register } from 'prom-client'
import { v4 as uuidv4 } from 'uuid'

import { defaultConfig } from '~/common/config/config'
import { StallingValkeyProxy } from '~/common/redis/_tests/stalling-valkey-proxy'
import { waitForExpect } from '~/tests/helpers/expectations'

import { CyclotronJobInvocation } from '../../../types'
import { CyclotronJobQueuePostgresV2 } from '../../job-queue/job-queue-postgres-v2'
import { createSandboxEmailQueue } from './sandbox-email-queue'

const failedSesClaims = async (): Promise<number> => {
    const metric = await register.getSingleMetricAsString('cdp_rate_limiter_claim_total')
    const line = metric.split('\n').find((l) => l.includes('limiter="ses"') && l.includes('result="valkey_error"'))
    return line ? Number(line.trim().split(' ').pop()) : 0
}

const answerWithin = <T>(work: Promise<T>, ms: number): Promise<T | 'no answer'> => {
    let gaveUp: NodeJS.Timeout | undefined
    return Promise.race([
        work,
        new Promise<'no answer'>((resolve) => {
            gaveUp = setTimeout(() => resolve('no answer'), ms)
        }),
    ]).finally(() => clearTimeout(gaveUp))
}

describe('createSandboxEmailQueue', () => {
    jest.setTimeout(60_000)

    let store: StallingValkeyProxy
    let queue: CyclotronJobQueuePostgresV2
    let cyclotron: Pool
    let invocation: CyclotronJobInvocation
    let consumed: string[]

    beforeEach(async () => {
        store = new StallingValkeyProxy({ host: defaultConfig.CDP_REDIS_HOST, port: defaultConfig.CDP_REDIS_PORT })
        queue = createSandboxEmailQueue({
            ...defaultConfig,
            SES_RATE_LIMITER_VALKEY_HOST: '127.0.0.1',
            SES_RATE_LIMITER_VALKEY_PORT: await store.start(),
            SES_RATE_LIMITER_VALKEY_PASSWORD: defaultConfig.CDP_REDIS_PASSWORD,
            SES_RATE_LIMITER_VALKEY_TLS: false,
            CDP_CYCLOTRON_BATCH_DELAY_MS: 50,
            CDP_SES_RATE_LIMIT_THROTTLED_POLL_DELAY_MS: 50,
        })
        cyclotron = new Pool({ connectionString: defaultConfig.CYCLOTRON_NODE_DATABASE_URL })
        invocation = {
            id: uuidv4(),
            teamId: 1,
            functionId: uuidv4(),
            queue: 'emailsandbox',
            queuePriority: 0,
            state: { globals: {}, timings: [], vmState: { bytecodes: {}, stack: [], upvalues: [] } },
        }
        consumed = []
        await queue.startAsConsumer('emailsandbox', (invocations) => {
            consumed.push(...invocations.map((i) => i.id))
            return Promise.resolve({ backgroundTask: Promise.resolve() })
        })
    })

    afterEach(async () => {
        await answerWithin(queue.stopConsumer(), 10_000)
        await queue.stopProducer()
        await cyclotron.query('DELETE FROM cyclotron_jobs WHERE id = $1', [invocation.id])
        await cyclotron.end()
        store.stop()
    })

    it('keeps polling while the SES bucket store stops answering, dequeues once it answers, and stops promptly', async () => {
        store.stopAnswering()
        const failedBefore = await failedSesClaims()
        await queue.queueInvocations([invocation])

        await waitForExpect(
            async () => expect(await failedSesClaims()).toBeGreaterThanOrEqual(failedBefore + 2),
            20_000
        )
        expect(consumed).not.toContain(invocation.id)

        store.answerNewConnections()
        await waitForExpect(() => expect(consumed).toContain(invocation.id), 30_000)

        store.stopAnswering()
        expect(await answerWithin(queue.stopConsumer(), 10_000)).not.toBe('no answer')
    })
})
