import { randomUUID } from 'crypto'
import { register } from 'prom-client'

import { defaultConfig } from '~/common/config/config'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { TeamManager } from '~/common/utils/team-manager'

import { Team } from '../../../types'
import { createHogFunction } from '../../_tests/fixtures'
import { CyclotronJobInvocation, HogFunctionType } from '../../types'
import { HogWatcherConfig, HogWatcherService, HogWatcherState } from '../monitoring/hog-watcher.service'
import { createCrashGuardValkeyPool } from './crash-guard'
import {
    QuarantineAutoDisableConfig,
    QuarantineAutoDisableService,
    createQuarantineAutoDisable,
    recentlyQuarantinedKey,
} from './quarantine-auto-disable'

jest.mock('~/common/utils/posthog', () => ({
    ...jest.requireActual('~/common/utils/posthog'),
    captureTeamEvent: jest.fn(),
}))

const mockCaptureTeamEvent: jest.Mock = require('~/common/utils/posthog').captureTeamEvent

const WINDOW_SECONDS = 60 * 60

const WATCHER_CONFIG: HogWatcherConfig = {
    hogCostTimingLowerMs: 50,
    hogCostTimingUpperMs: 550,
    hogCostTiming: 100,
    asyncCostTimingLowerMs: 100,
    asyncCostTimingUpperMs: 5000,
    asyncCostTiming: 20,
    sendEvents: true,
    bucketSize: 10000,
    refillRate: 10,
    ttl: 86400,
    automaticallyDisableFunctions: true,
    thresholdDegraded: 0.8,
    stateLockTtl: 60,
    observeResultsBufferTimeMs: 500,
    observeResultsBufferMaxResults: 500,
}

describe('QuarantineAutoDisableService', () => {
    const team = { id: 2, uuid: 'team-uuid', organization_id: 'org-id' } as Team
    const teamManager = { getTeam: () => Promise.resolve(team) } as unknown as TeamManager

    let valkey: RedisV2
    let hogWatcher: HogWatcherService
    let hogWatcherMirror: HogWatcherService
    let hogFunction: HogFunctionType
    let now: number

    const counter = async (name: string, labels: Record<string, string> = {}): Promise<number> =>
        (await register.getSingleMetric(name)!.get()).values.find((v) =>
            Object.entries(labels).every(([k, value]) => v.labels[k] === value)
        )?.value ?? 0

    beforeAll(() => {
        valkey = createCrashGuardValkeyPool(defaultConfig)
        const redis = createRedisV2PoolFromConfig({
            connection: {
                url: defaultConfig.CDP_REDIS_HOST,
                options: { port: defaultConfig.CDP_REDIS_PORT, password: defaultConfig.CDP_REDIS_PASSWORD },
            },
            poolMinSize: 1,
            poolMaxSize: 2,
        })
        hogWatcher = new HogWatcherService(teamManager, WATCHER_CONFIG, redis)
        hogWatcherMirror = new HogWatcherService(teamManager, { ...WATCHER_CONFIG, sendEvents: false }, valkey)
    })

    beforeEach(() => {
        now = 1_720_000_000_000
        jest.spyOn(Date, 'now').mockImplementation(() => now)
        hogFunction = createHogFunction({ id: randomUUID(), team_id: team.id, name: 'Quarantined destination' })
        mockCaptureTeamEvent.mockClear()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    const service = (
        config: Partial<QuarantineAutoDisableConfig> = {},
        pool: RedisV2 = valkey
    ): QuarantineAutoDisableService =>
        new QuarantineAutoDisableService(
            {
                valkey: pool,
                getHogFunction: (id) => Promise.resolve(id === hogFunction.id ? hogFunction : null),
                hogWatcher,
                hogWatcherMirror,
            },
            { threshold: 3, windowSeconds: WINDOW_SECONDS, autoDisable: true, ...config }
        )

    const quarantinedInvocation = (id: string, functionId = hogFunction.id): CyclotronJobInvocation => ({
        id,
        teamId: team.id,
        functionId,
        state: null,
        queue: 'hogdlq',
        queuePriority: 0,
    })

    const stateChangeEvents = () =>
        mockCaptureTeamEvent.mock.calls.filter(([, event]) => event === 'hog_function_state_change')

    it.each([
        ['disables the function at the threshold', {}, [0, 0, 0], ['a', 'b', 'c'], undefined, HogWatcherState.disabled],
        ['keeps the function healthy below the threshold', {}, [0, 0], ['a', 'b'], undefined, HogWatcherState.healthy],
        [
            'keeps the function healthy when the quarantines spread over more than the window',
            {},
            [0, (WINDOW_SECONDS / 2) * 1000, (WINDOW_SECONDS + 1) * 1000],
            ['a', 'b', 'c'],
            undefined,
            HogWatcherState.healthy,
        ],
        // The dead letter topic is at least once, so the same invocation can be quarantined twice.
        [
            'counts a duplicate quarantine of an invocation once',
            {},
            [0, 0, 0],
            ['a', 'a', 'b'],
            undefined,
            HogWatcherState.healthy,
        ],
        [
            'does not disable while automatic disabling is off',
            { autoDisable: false },
            [0, 0, 0],
            ['a', 'b', 'c'],
            undefined,
            HogWatcherState.healthy,
        ],
        [
            'leaves a forcefully degraded function alone',
            {},
            [0, 0, 0],
            ['a', 'b', 'c'],
            HogWatcherState.forcefully_degraded,
            HogWatcherState.forcefully_degraded,
        ],
        [
            'leaves a forcefully disabled function alone',
            {},
            [0, 0, 0],
            ['a', 'b', 'c'],
            HogWatcherState.forcefully_disabled,
            HogWatcherState.forcefully_disabled,
        ],
        [
            'leaves an already disabled function alone',
            {},
            [0, 0, 0],
            ['a', 'b', 'c'],
            HogWatcherState.disabled,
            HogWatcherState.disabled,
        ],
    ] as const)('%s', async (_, config, offsetsMs, ids, initialState, expectedState) => {
        if (initialState !== undefined) {
            await hogWatcher.forceStateChange(hogFunction, initialState)
            await hogWatcherMirror.forceStateChange(hogFunction, initialState)
            mockCaptureTeamEvent.mockClear()
        }
        const disabledBefore = await counter('cdp_functions_auto_disabled_total')
        const start = now
        const quarantines = service(config)

        for (const [i, id] of ids.entries()) {
            now = start + offsetsMs[i]
            await quarantines.observe([quarantinedInvocation(`${hogFunction.id}-${id}`)])
        }

        const disabled = expectedState === HogWatcherState.disabled && initialState === undefined
        expect((await hogWatcher.getPersistedState(hogFunction.id)).state).toEqual(expectedState)
        expect((await hogWatcherMirror.getPersistedState(hogFunction.id)).state).toEqual(expectedState)
        expect(await counter('cdp_functions_auto_disabled_total')).toEqual(disabledBefore + (disabled ? 1 : 0))
        expect(stateChangeEvents()).toEqual(
            disabled
                ? [
                      [
                          team,
                          'hog_function_state_change',
                          expect.objectContaining({
                              hog_function_id: hogFunction.id,
                              state: 'disabled',
                              previous_state: 'healthy',
                          }),
                      ],
                  ]
                : []
        )
    })

    it('counts a function as newly quarantined once per 10 minutes', async () => {
        const other = randomUUID()
        const newBefore = await counter('cdp_quarantined_functions_new_total')

        await service().observe([quarantinedInvocation('a'), quarantinedInvocation('b', other)])
        await service().observe([quarantinedInvocation('c'), quarantinedInvocation('d', other)])

        expect(await counter('cdp_quarantined_functions_new_total')).toEqual(newBefore + 2)
        const ttl = await valkey.useClient({ name: 'test' }, (client) =>
            client.ttl(recentlyQuarantinedKey(hogFunction.id))
        )
        expect(ttl).toBeGreaterThan(0)
        expect(ttl).toBeLessThanOrEqual(10 * 60)
    })

    it('resolves without a disable when Valkey is unreachable', async () => {
        const unreachable = createCrashGuardValkeyPool({ ...defaultConfig, CDP_VALKEY_PORT: 1 })
        const unavailableBefore = await counter('cdp_quarantine_disable_checks_total', { outcome: 'unavailable' })

        await expect(
            service({ threshold: 1 }, unreachable).observe([quarantinedInvocation('a')])
        ).resolves.toBeUndefined()

        expect(await counter('cdp_quarantine_disable_checks_total', { outcome: 'unavailable' })).toEqual(
            unavailableBefore + 1
        )
        expect((await hogWatcher.getPersistedState(hogFunction.id)).state).toEqual(HogWatcherState.healthy)
    })

    it.each([
        ['CDP_QUARANTINE_DISABLE_THRESHOLD', 0],
        ['CDP_QUARANTINE_DISABLE_WINDOW_SECONDS', 1.5],
    ])('refuses %s set to %p', (name, value) => {
        expect(() =>
            createQuarantineAutoDisable(
                { ...defaultConfig, [name]: value },
                {
                    valkey,
                    getHogFunction: () => Promise.resolve(null),
                    hogWatcher,
                    hogWatcherMirror,
                }
            )
        ).toThrow(name)
    })
})
