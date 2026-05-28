import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS, slackIntegrationLogic } from './slackIntegrationLogic'

const FIXED_NOW = new Date('2026-01-01T12:00:00Z')

const channel = (id: string, name: string): Record<string, unknown> => ({
    id,
    name,
    is_private: false,
    is_member: true,
    is_ext_shared: false,
    is_private_without_access: false,
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

describe('slackIntegrationLogic — channel search by name', () => {
    let logic: ReturnType<typeof slackIntegrationLogic.build>
    let receivedSearchParam: string | null

    beforeEach(() => {
        receivedSearchParam = null
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/channels': (req) => {
                    const url = new URL(req.url.toString())
                    const search = url.searchParams.get('search')
                    const channelId = url.searchParams.get('channel_id')
                    if (channelId) {
                        // direct ID lookup — the buggy code path; never matches a name
                        return [200, { channels: [] }]
                    }
                    if (search !== null) {
                        receivedSearchParam = search
                        if (search.toLowerCase() === 'eng') {
                            return [
                                200,
                                {
                                    channels: [channel('C3', 'engineering')],
                                    lastRefreshedAt: '2026-01-01T12:00:00Z',
                                    has_more: false,
                                },
                            ]
                        }
                        return [200, { channels: [], has_more: false }]
                    }
                    // initial load returns only the first page — `engineering` is *not* in it
                    return [
                        200,
                        {
                            channels: [channel('C1', 'general'), channel('C2', 'random')],
                            lastRefreshedAt: '2026-01-01T12:00:00Z',
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

    it('exposes a loadSlackChannelsBySearch action that surfaces server-side name matches', async () => {
        expect(typeof logic.actions.loadSlackChannelsBySearch).toBe('function')

        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()

        // The initial page does *not* contain the engineering channel — exactly the
        // workspaces-with-many-channels case where name search has been silently failing.
        expect(logic.values.slackChannels.map((c) => c.id)).not.toContain('C3')

        await expectLogic(logic, () => {
            logic.actions.loadSlackChannelsBySearch('eng')
        }).toFinishAllListeners()

        expect(receivedSearchParam).toBe('eng')
        expect(logic.values.slackChannels.map((c) => c.id)).toContain('C3')
        const engineering = logic.values.slackChannels.find((c) => c.id === 'C3')
        expect(engineering?.name).toBe('engineering')
    })

    it('clearSlackChannelsBySearch drops stale search results from slackChannels', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.loadSlackChannelsBySearch('eng')
        }).toFinishAllListeners()
        expect(logic.values.slackChannels.map((c) => c.id)).toContain('C3')

        await expectLogic(logic, () => {
            logic.actions.clearSlackChannelsBySearch()
        }).toFinishAllListeners()

        // Search results are gone, only the initial page survives.
        expect(logic.values.slackChannels.map((c) => c.id)).toEqual(['C1', 'C2'])
    })
})
