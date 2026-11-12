import { randomUUID } from 'crypto'
import { register } from 'prom-client'

import { defaultConfig } from '~/common/config/config'
import { RedisV2 } from '~/common/redis/redis-v2'

import { CyclotronJobInvocation } from '../../types'
import { createCrashGuardValkeyPool } from './crash-guard'
import { QuarantineTracker, QuarantineTrackerConfig, createQuarantineTracker } from './quarantine-tracker'

const WINDOW_SECONDS = 60 * 60

describe('QuarantineTracker', () => {
    let valkey: RedisV2
    let functionId: string
    let now: number
    let trackers: QuarantineTracker[]

    // The charts alert reads this gauge, so a rename of the metric or its labels silences it.
    const reported = async (id: string) =>
        (await register.getSingleMetric('cdp_quarantined_functions')!.get()).values
            .filter((v) => v.labels.function_id === id)
            .map(({ labels, value }) => ({ labels, value }))

    beforeAll(() => {
        valkey = createCrashGuardValkeyPool(defaultConfig)
    })

    beforeEach(() => {
        now = 1_720_000_000_000
        jest.spyOn(Date, 'now').mockImplementation(() => now)
        functionId = randomUUID()
        trackers = []
    })

    afterEach(() => {
        trackers.forEach((tracker) => tracker.stop())
        jest.restoreAllMocks()
    })

    const tracker = (config: Partial<QuarantineTrackerConfig> = {}, pool: RedisV2 = valkey): QuarantineTracker => {
        const created = new QuarantineTracker(pool, { threshold: 3, windowSeconds: WINDOW_SECONDS, ...config })
        trackers.push(created)
        return created
    }

    const quarantinedInvocation = (id: string, teamId = 2): CyclotronJobInvocation => ({
        id: `${functionId}-${id}`,
        teamId,
        functionId,
        state: null,
        queue: 'hogdlq',
        queuePriority: 0,
    })

    it.each([
        ['reports a function at the threshold with its team', [0, 0, 0], ['a', 'b', 'c'], 0, 3],
        ['leaves out a function below the threshold', [0, 0], ['a', 'b'], 0, null],
        [
            'leaves out a function whose quarantines spread over more than the window',
            [0, (WINDOW_SECONDS / 2) * 1000, (WINDOW_SECONDS + 1) * 1000],
            ['a', 'b', 'c'],
            0,
            null,
        ],
        ['leaves out a function once its window passed', [0, 0, 0], ['a', 'b', 'c'], (WINDOW_SECONDS + 1) * 1000, null],
        // The dead letter topic is at least once, so the same invocation can be quarantined twice.
        ['counts a duplicate quarantine of an invocation once', [0, 0, 0], ['a', 'a', 'b'], 0, null],
    ] as const)('%s', async (_, offsetsMs, ids, scrapedAfterMs, value) => {
        const start = now
        const quarantines = tracker()

        for (const [i, id] of ids.entries()) {
            now = start + offsetsMs[i]
            await quarantines.observe([quarantinedInvocation(id)])
        }
        now += scrapedAfterMs

        expect(await reported(functionId)).toEqual(
            value === null ? [] : [{ labels: { function_id: functionId, team_id: '2' }, value }]
        )
    })

    it('reports nothing and still lets the quarantine commit when Valkey is unreachable', async () => {
        const unreachable = createCrashGuardValkeyPool({ ...defaultConfig, CDP_VALKEY_PORT: 1 })
        const quarantines = tracker({ threshold: 1 }, unreachable)

        await expect(quarantines.observe([quarantinedInvocation('a')])).resolves.toBeUndefined()

        expect(await reported(functionId)).toEqual([])
    })

    it.each([
        ['CDP_QUARANTINE_ESCALATION_THRESHOLD', 0],
        ['CDP_QUARANTINE_ESCALATION_WINDOW_SECONDS', 1.5],
    ])('refuses %s set to %p', (name, value) => {
        expect(() => createQuarantineTracker({ ...defaultConfig, [name]: value }, valkey)).toThrow(name)
    })
})
