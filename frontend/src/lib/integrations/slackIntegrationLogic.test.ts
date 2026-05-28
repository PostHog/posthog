import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SlackChannelType } from '~/types'

import {
    RECENTLY_SUBSCRIBED_SLACK_CHANNELS_LIMIT,
    SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS,
    slackIntegrationLogic,
} from './slackIntegrationLogic'

const FIXED_NOW = new Date('2026-01-01T12:00:00Z')

describe('slackIntegrationLogic — loadAllSlackChannels search & pagination', () => {
    let logic: ReturnType<typeof slackIntegrationLogic.build>
    let lastChannelsQuery: Record<string, string> = {}
    let nextChannelsResponse: { id: string; name: string }[] = [
        { id: 'C1', name: 'general' },
        { id: 'C2', name: 'engineering' },
    ]

    const buildChannel = (id: string, name: string): SlackChannelType => ({
        id,
        name,
        is_private: false,
        is_member: true,
        is_ext_shared: false,
        is_private_without_access: false,
    })

    beforeEach(() => {
        lastChannelsQuery = {}
        nextChannelsResponse = [
            { id: 'C1', name: 'general' },
            { id: 'C2', name: 'engineering' },
        ]
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/channels': (req) => {
                    lastChannelsQuery = Object.fromEntries(req.url.searchParams.entries())
                    return [
                        200,
                        {
                            channels: nextChannelsResponse.map((c) => buildChannel(c.id, c.name)),
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

    it('forwards search to the channels endpoint when search is provided', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels(false, 'eng')
        }).toFinishAllListeners()

        expect(lastChannelsQuery.search).toBe('eng')
        // No explicit limit — the picker defers to the backend default so the initial dropdown
        // stays light and anything past the default falls through to server-side search.
        expect(lastChannelsQuery.limit).toBeUndefined()
        expect(lastChannelsQuery.force_refresh).toBe('false')
        expect(logic.values.allSlackChannels?.has_more).toBe(true)
    })

    it('still works with no arguments (backwards compatible)', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()

        expect(lastChannelsQuery.search).toBe('')
        expect(lastChannelsQuery.limit).toBeUndefined()
    })

    it('reloads the full list when a search-then-clear sequence runs', async () => {
        // First, narrow the cache with a search — server returns only the matching subset.
        nextChannelsResponse = [{ id: 'C2', name: 'engineering' }]
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels(false, 'eng')
        }).toFinishAllListeners()

        expect(lastChannelsQuery.search).toBe('eng')
        expect(logic.values.slackChannels.map((c) => c.id)).toEqual(['C2'])

        // Then clear: empty search must re-fetch and restore the full visible set.
        nextChannelsResponse = [
            { id: 'C1', name: 'general' },
            { id: 'C2', name: 'engineering' },
        ]
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()

        expect(lastChannelsQuery.search).toBe('')
        expect(logic.values.slackChannels.map((c) => c.id)).toEqual(['C1', 'C2'])
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

const fixtureChannel = (id: string, name: string, extra: Partial<SlackChannelType> = {}): SlackChannelType => ({
    id,
    name,
    is_private: false,
    is_ext_shared: false,
    is_member: true,
    ...extra,
})

describe('slackIntegrationLogic — recently subscribed channels', () => {
    let logic: ReturnType<typeof slackIntegrationLogic.build>
    const allChannels = [
        fixtureChannel('C3', 'announcements'),
        fixtureChannel('C1', 'alerts'),
        fixtureChannel('C2', 'general'),
    ]

    beforeEach(() => {
        // kea-localstorage hydrates from localStorage on mount; clear so each test starts fresh.
        window.localStorage.clear()
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/channels': {
                    channels: allChannels,
                    lastRefreshedAt: '2026-01-01T00:00:00Z',
                },
            },
        })
        initKeaTests()
        logic = slackIntegrationLogic({ id: 1 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        window.localStorage.clear()
    })

    it('sorts channels alphabetically by name when no recency is recorded', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        })
            .toFinishAllListeners()
            .toMatchValues({
                slackChannels: [
                    expect.objectContaining({ id: 'C1', name: 'alerts' }),
                    expect.objectContaining({ id: 'C3', name: 'announcements' }),
                    expect.objectContaining({ id: 'C2', name: 'general' }),
                ],
            })
    })

    it('puts recently subscribed channels first (most recent first), then alphabetical', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
            logic.actions.recordSubscribedChannel('C2')
            logic.actions.recordSubscribedChannel('C3')
        })
            .toFinishAllListeners()
            .toMatchValues({
                slackChannels: [
                    expect.objectContaining({ id: 'C3', name: 'announcements' }),
                    expect.objectContaining({ id: 'C2', name: 'general' }),
                    expect.objectContaining({ id: 'C1', name: 'alerts' }),
                ],
            })
    })

    it('deduplicates and moves an already-recorded channel back to the top', async () => {
        await expectLogic(logic, () => {
            logic.actions.recordSubscribedChannel('C1')
            logic.actions.recordSubscribedChannel('C2')
            logic.actions.recordSubscribedChannel('C1')
        }).toMatchValues({
            recentlySubscribedChannelIds: ['C1', 'C2'],
        })
    })

    it('caps the recency list at the configured limit and drops the oldest entries', async () => {
        await expectLogic(logic, () => {
            for (let i = 0; i < RECENTLY_SUBSCRIBED_SLACK_CHANNELS_LIMIT + 5; i++) {
                logic.actions.recordSubscribedChannel(`C${i}`)
            }
        }).toMatchValues({
            recentlySubscribedChannelIds: expect.arrayContaining([]),
        })
        expect(logic.values.recentlySubscribedChannelIds).toHaveLength(RECENTLY_SUBSCRIBED_SLACK_CHANNELS_LIMIT)
        expect(logic.values.recentlySubscribedChannelIds[0]).toBe(`C${RECENTLY_SUBSCRIBED_SLACK_CHANNELS_LIMIT + 4}`)
        expect(logic.values.recentlySubscribedChannelIds).not.toContain('C0')
    })

    it('ignores empty channel ids', async () => {
        await expectLogic(logic, () => {
            logic.actions.recordSubscribedChannel('C1')
            logic.actions.recordSubscribedChannel('')
        }).toMatchValues({
            recentlySubscribedChannelIds: ['C1'],
        })
    })
})
