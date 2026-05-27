import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS, slackIntegrationLogic } from './slackIntegrationLogic'

const FIXED_NOW = new Date('2026-01-01T12:00:00Z')

describe('slackIntegrationLogic — getChannelRefreshButtonDisabledReason', () => {
    let logic: ReturnType<typeof slackIntegrationLogic.build>
    let lastRefreshedAt: string

    beforeEach(() => {
        // Only fake `Date` so dayjs() reads a fixed wall clock; keep timers real so kea-test-utils async helpers run.
        jest.useFakeTimers({
            now: FIXED_NOW,
            doNotFake: [
                'hrtime',
                'nextTick',
                'performance',
                'queueMicrotask',
                'requestAnimationFrame',
                'cancelAnimationFrame',
                'requestIdleCallback',
                'cancelIdleCallback',
                'setImmediate',
                'clearImmediate',
                'setInterval',
                'clearInterval',
                'setTimeout',
                'clearTimeout',
            ],
        })
        lastRefreshedAt = ''
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/channels': () => [200, { channels: [], lastRefreshedAt }],
            },
        })
        initKeaTests()
        logic = slackIntegrationLogic({ id: 1 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    const refreshAt = async (timestamp: string): Promise<void> => {
        lastRefreshedAt = timestamp
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()
    }

    it.each<[string, number, boolean]>([
        ['stays disabled immediately after a refresh', 0, false],
        ['stays disabled just before the cooldown elapses', SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS - 1, false],
        ['enables once the cooldown has elapsed', SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS + 1, true],
    ])('refresh button %s', async (_label, secondsAgo, expectEnabled) => {
        await refreshAt(dayjs(FIXED_NOW).subtract(secondsAgo, 'seconds').toISOString())
        const reason = logic.values.getChannelRefreshButtonDisabledReason()
        if (expectEnabled) {
            expect(reason).toBe('')
        } else {
            expect(reason).not.toBe('')
        }
    })
})

describe('slackIntegrationLogic — loadAllSlackChannels pagination', () => {
    let logic: ReturnType<typeof slackIntegrationLogic.build>
    let forceRefreshByOffset: Record<string, string | null>

    const channel = (id: string): { id: string; name: string; is_private: boolean; is_member: boolean } => ({
        id,
        name: id,
        is_private: false,
        is_member: true,
    })

    beforeEach(() => {
        forceRefreshByOffset = {}
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/channels': (req) => {
                    const offset = Number(req.url.searchParams.get('offset') || 0)
                    forceRefreshByOffset[offset] = req.url.searchParams.get('force_refresh')
                    // Three pages of 200; the third is partial, so has_more flips false.
                    if (offset === 0) {
                        return [200, { channels: [channel('a')], lastRefreshedAt: '', has_more: true }]
                    }
                    if (offset === 200) {
                        return [200, { channels: [channel('b')], lastRefreshedAt: '', has_more: true }]
                    }
                    return [200, { channels: [channel('zzz-sentry-alerts')], lastRefreshedAt: '', has_more: false }]
                },
            },
        })
        initKeaTests()
        logic = slackIntegrationLogic({ id: 1 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('walks every page and accumulates channels beyond the first', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()

        expect(logic.values.slackChannels.map((c) => c.id)).toEqual(['a', 'b', 'zzz-sentry-alerts'])
    })

    it('only forces a refresh on the first page', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels(true)
        }).toFinishAllListeners()

        expect(forceRefreshByOffset['0']).toBe('true')
        expect(forceRefreshByOffset['200']).toBe('false')
        expect(forceRefreshByOffset['400']).toBe('false')
    })
})
