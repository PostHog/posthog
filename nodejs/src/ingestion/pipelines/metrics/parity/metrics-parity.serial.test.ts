import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'fs'
import Redis from 'ioredis'
import { join } from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { PARITY_REDIS_URL, runMetricsParityScenario } from './parity-harness'
import { buildMetricsParityScenarios } from './parity-scenarios'
import type { MetricsParityFixture } from './parity-types'

// The harness drives `handleKafkaBatch` directly, so no Kafka consumer connects.
jest.mock('~/common/kafka/consumer/consumer-v2', () => ({
    KafkaConsumerV2: jest.fn().mockImplementation(() => ({
        connect: jest.fn(),
        disconnect: jest.fn(),
        isHealthy: jest.fn(),
    })),
}))

// `rust/metrics-ingestion` replays these files. Re-record only for an intended behavior change, and port it to Rust.
const FIXTURE_DIR = join(__dirname, 'fixtures')
const RECORD = process.env.METRICS_PARITY_RECORD === '1'

jest.setTimeout(60_000)

function fixtureFiles(): string[] {
    return existsSync(FIXTURE_DIR)
        ? readdirSync(FIXTURE_DIR)
              .filter((file) => file.endsWith('.json'))
              .sort()
        : []
}

describe('metrics ingestion parity corpus', () => {
    let redis: InstanceType<typeof Redis>

    beforeAll(() => {
        redis = new Redis(PARITY_REDIS_URL)
    })

    afterAll(async () => {
        await redis.quit()
    })

    async function run(scenario: MetricsParityFixture['scenario']): Promise<MetricsParityFixture['expected']> {
        await redis.flushdb()
        jest.useFakeTimers({
            now: scenario.batch_now_ms[0] ?? 0,
            doNotFake: [
                'setTimeout',
                'clearTimeout',
                'setInterval',
                'clearInterval',
                'setImmediate',
                'clearImmediate',
                'nextTick',
                'queueMicrotask',
                'hrtime',
                'performance',
            ],
        })
        try {
            return await runMetricsParityScenario(scenario, (nowMs) => jest.setSystemTime(nowMs))
        } finally {
            jest.useRealTimers()
        }
    }

    if (RECORD) {
        it('records the corpus', async () => {
            rmSync(FIXTURE_DIR, { recursive: true, force: true })
            mkdirSync(FIXTURE_DIR, { recursive: true })
            for (const scenario of buildMetricsParityScenarios()) {
                const fixture: MetricsParityFixture = { scenario, expected: await run(scenario) }
                writeFileSync(join(FIXTURE_DIR, `${scenario.name}.json`), JSON.stringify(fixture, null, 1) + '\n')
            }
        })
        return
    }

    it('has fixtures', () => {
        expect(fixtureFiles().length).toBeGreaterThan(0)
    })

    it.each(fixtureFiles())('%s', async (file) => {
        const fixture: MetricsParityFixture = parseJSON(readFileSync(join(FIXTURE_DIR, file), 'utf8'))
        expect(await run(fixture.scenario)).toStrictEqual(fixture.expected)
    })
})
