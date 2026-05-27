import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS, slackIntegrationLogic } from './slackIntegrationLogic'

const FIXED_NOW = new Date('2026-01-01T12:00:00Z')

describe('slackIntegrationLogic — loadAllSlackChannels search & pagination', () => {
    let logic: ReturnType<typeof slackIntegrationLogic.build>
    let lastChannelsQuery: Record<string, string> = {}

    beforeEach(() => {
        lastChannelsQuery = {}
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/channels': (req) => {
                    lastChannelsQuery = Object.fromEntries(req.url.searchParams.entries())
                    return [
                        200,
                        {
                            channels: [
                                {
                                    id: 'C1',
                                    name: 'general',
                                    is_private: false,
                                    is_member: true,
                                    is_ext_shared: false,
                                    is_private_without_access: false,
                                },
                            ],
                            lastRefreshedAt: '2026-01-01T00:00:00Z',
                            has_more: true,
                        },
                    ]
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

    it('forwards search and limit to the channels endpoint when search is provided', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels(false, 'eng')
        }).toFinishAllListeners()

        expect(lastChannelsQuery.search).toBe('eng')
        expect(lastChannelsQuery.limit).toBe('200')
        expect(lastChannelsQuery.force_refresh).toBe('false')
        expect(logic.values.allSlackChannels?.has_more).toBe(true)
    })

    it('still works with no arguments (backwards compatible)', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()

        expect(lastChannelsQuery.search).toBe('')
        expect(lastChannelsQuery.limit).toBe('200')
    })
})

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
