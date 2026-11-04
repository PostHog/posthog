import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'fs'
import Redis from 'ioredis'
import { join } from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import {
    CURRENT_CLASSES,
    FRAMEWORK_CLASSES,
    PARITY_REDIS_URL,
    type ParityConsumerClasses,
    runParityScenario,
} from './parity-harness'
import { buildParityScenarios } from './parity-scenarios'
import type { ParityFixture } from './parity-types'

// `rust/logs-ingestion` replays these files. Re-record only for an intended behavior change, and port it to Rust.
const FIXTURE_DIR = join(__dirname, 'fixtures', 'scenarios')
const RECORD = process.env.LOGS_PARITY_RECORD === '1'

jest.setTimeout(60_000)

function fixtureFiles(): string[] {
    return existsSync(FIXTURE_DIR)
        ? readdirSync(FIXTURE_DIR)
              .filter((file) => file.endsWith('.json'))
              .sort()
        : []
}

describe('logs ingestion parity corpus', () => {
    let redis: InstanceType<typeof Redis>

    beforeAll(() => {
        redis = new Redis(PARITY_REDIS_URL)
    })

    afterAll(async () => {
        await redis.quit()
    })

    async function run(
        fixture: ParityFixture['scenario'],
        classes: ParityConsumerClasses
    ): Promise<ParityFixture['expected']> {
        await redis.flushdb()
        jest.useFakeTimers({
            now: fixture.batch_now_ms[0] ?? 0,
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
            return await runParityScenario(fixture, (nowMs) => jest.setSystemTime(nowMs), classes)
        } finally {
            jest.useRealTimers()
        }
    }

    if (RECORD) {
        it('records the corpus', async () => {
            rmSync(FIXTURE_DIR, { recursive: true, force: true })
            mkdirSync(FIXTURE_DIR, { recursive: true })
            for (const scenario of await buildParityScenarios()) {
                // The framework consumer has the produce-replay fix that the corpus expects.
                const expected = await run(scenario, FRAMEWORK_CLASSES)
                const fixture: ParityFixture = { scenario, expected }
                writeFileSync(join(FIXTURE_DIR, `${scenario.name}.json`), JSON.stringify(fixture, null, 1) + '\n')
            }
        })
        return
    }

    it('has fixtures', () => {
        expect(fixtureFiles().length).toBeGreaterThan(0)
    })

    describe.each([
        ['LogsIngestionConsumer', CURRENT_CLASSES],
        ['LogsIngestionFrameworkConsumer', FRAMEWORK_CLASSES],
    ])('%s', (_, classes) => {
        for (const file of fixtureFiles()) {
            it(file, async () => {
                const fixture: ParityFixture = parseJSON(readFileSync(join(FIXTURE_DIR, file), 'utf8'))
                expect(await run(fixture.scenario, classes)).toStrictEqual(fixture.expected)
            })
        }
    })
})
