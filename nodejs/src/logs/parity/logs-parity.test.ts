import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'fs'
import Redis from 'ioredis'
import { join } from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { runParityScenario } from './parity-harness'
import { buildParityScenarios } from './parity-scenarios'
import type { ParityFixture } from './parity-types'

/**
 * Replays the shared parity corpus against the logs consumer. `rust/logs-ingestion` replays the same
 * files, so a fixture diff here means the two implementations no longer agree.
 *
 * `LOGS_PARITY_RECORD=1` rebuilds the inputs and rewrites the expected outputs from this consumer.
 * Re-record only when a behavior change is intended, and port the change to Rust in the same PR.
 */
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
    let redis: Redis

    beforeAll(() => {
        redis = new Redis('redis://127.0.0.1:6379')
    })

    afterAll(async () => {
        await redis.quit()
    })

    async function run(fixture: ParityFixture['scenario']): Promise<ParityFixture['expected']> {
        await redis.flushdb()
        jest.useFakeTimers({
            now: fixture.now_ms,
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
            return await runParityScenario(fixture)
        } finally {
            jest.useRealTimers()
        }
    }

    if (RECORD) {
        it('records the corpus', async () => {
            mkdirSync(FIXTURE_DIR, { recursive: true })
            for (const scenario of await buildParityScenarios()) {
                const expected = await run(scenario)
                const fixture: ParityFixture = { scenario, expected }
                writeFileSync(join(FIXTURE_DIR, `${scenario.name}.json`), JSON.stringify(fixture, null, 1) + '\n')
            }
        })
        return
    }

    it('has fixtures', () => {
        expect(fixtureFiles().length).toBeGreaterThan(0)
    })

    it.each(fixtureFiles())('%s', async (file) => {
        const fixture: ParityFixture = parseJSON(readFileSync(join(FIXTURE_DIR, file), 'utf8'))
        const actual = await run(fixture.scenario)
        expect(actual).toEqual(fixture.expected)
    })
})
