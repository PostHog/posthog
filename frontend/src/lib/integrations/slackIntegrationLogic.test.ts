import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SlackChannelType } from '~/types'

import {
    getRecentSlackChannelIds,
    RECENTLY_SUBSCRIBED_SLACK_CHANNELS_LIMIT,
    recordRecentSlackChannel,
} from './slackChannel'
import { SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS, slackIntegrationLogic } from './slackIntegrationLogic'

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
                '/api/environments/:team_id/integrations/:id/channels': ({ request }) => {
                    lastChannelsQuery = Object.fromEntries(new URL(request.url).searchParams.entries())
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

    it('loadSlackChannelByIdSuccess pins a channel into slackChannels so a subsequent bulk reload cannot drop it', async () => {
        // First, load a bulk page that does NOT include the channel we're about to pin.
        nextChannelsResponse = [{ id: 'C_BULK', name: 'bulk-channel' }]
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()
        expect(logic.values.slackChannels.map((c) => c.id)).toEqual(['C_BULK'])

        // Now pin an off-page channel via the loader's auto-generated success action — this is
        // exactly what the picker does on selection to keep the channel resolvable through any
        // subsequent bulk reload triggered by LemonInputSelect's setInputValue('') side-effect.
        logic.actions.loadSlackChannelByIdSuccess(buildChannel('C_OFFPAGE', 'off-page-channel'))
        expect(logic.values.slackChannels.map((c) => c.id).sort()).toEqual(['C_BULK', 'C_OFFPAGE'])

        // Trigger a bulk reload that returns a fresh page still not including the pinned channel.
        nextChannelsResponse = [{ id: 'C_BULK2', name: 'bulk-channel-2' }]
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()

        // Without pinning, slackChannels would be ['C_BULK2']. With the pin held in
        // _fetchedSlackChannelById, the channel survives the reload.
        expect(logic.values.slackChannels.map((c) => c.id).sort()).toEqual(['C_BULK2', 'C_OFFPAGE'])
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

    it('isMemberOfSlackChannel returns null when the channel has not been loaded yet', () => {
        // Default selector state: no channels fetched, no by-id lookup landed. The picker uses
        // === false strict comparison to decide whether to show the "not in channel" warning, so
        // returning null here is what keeps that warning hidden until membership is actually known.
        expect(logic.values.isMemberOfSlackChannel('C_UNKNOWN')).toBeNull()
    })

    it('isMemberOfSlackChannel returns true/false once the channel is in slackChannels', async () => {
        nextChannelsResponse = [
            { id: 'CMEMBER', name: 'i-am-a-member' },
            // Override the helper's default by patching is_member after the fact.
        ]
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()

        // The fixture builds channels with is_member: true by default.
        expect(logic.values.isMemberOfSlackChannel('CMEMBER')).toBe(true)
        // Unrelated id still reads as not-yet-loaded.
        expect(logic.values.isMemberOfSlackChannel('CMISSING')).toBeNull()
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

describe('recentSlackChannels store', () => {
    beforeEach(() => {
        window.localStorage.clear()
    })

    afterEach(() => {
        window.localStorage.clear()
    })

    it('prepends, deduplicates, and moves an already-recorded channel back to the top', () => {
        recordRecentSlackChannel(1, 'C1')
        recordRecentSlackChannel(1, 'C2')
        recordRecentSlackChannel(1, 'C1')
        expect(getRecentSlackChannelIds(1)).toEqual(['C1', 'C2'])
    })

    it('persists to localStorage so the recency survives a fresh read', () => {
        recordRecentSlackChannel(1, 'C7')
        // A brand new read (no in-memory state) must see the persisted value.
        expect(getRecentSlackChannelIds(1)).toEqual(['C7'])
    })

    it('scopes recency per integration id', () => {
        recordRecentSlackChannel(1, 'C1')
        recordRecentSlackChannel(2, 'C2')
        expect(getRecentSlackChannelIds(1)).toEqual(['C1'])
        expect(getRecentSlackChannelIds(2)).toEqual(['C2'])
    })

    it('caps the recency list at the configured limit and drops the oldest entries', () => {
        for (let i = 0; i < RECENTLY_SUBSCRIBED_SLACK_CHANNELS_LIMIT + 5; i++) {
            recordRecentSlackChannel(1, `C${i}`)
        }
        const ids = getRecentSlackChannelIds(1)
        expect(ids).toHaveLength(RECENTLY_SUBSCRIBED_SLACK_CHANNELS_LIMIT)
        expect(ids[0]).toBe(`C${RECENTLY_SUBSCRIBED_SLACK_CHANNELS_LIMIT + 4}`)
        expect(ids).not.toContain('C0')
    })

    it('ignores empty channel ids', () => {
        recordRecentSlackChannel(1, 'C1')
        recordRecentSlackChannel(1, '')
        expect(getRecentSlackChannelIds(1)).toEqual(['C1'])
    })
})

describe('slackIntegrationLogic — slackChannelsForPicker', () => {
    let logic: ReturnType<typeof slackIntegrationLogic.build>
    const allChannels = [
        fixtureChannel('C3', 'announcements'),
        fixtureChannel('C1', 'alerts'),
        fixtureChannel('C2', 'general'),
    ]

    beforeEach(() => {
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

    it('leaves slackChannels in fetch order, sorting only the picker view', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()

        expect(logic.values.slackChannels.map((c) => c.id)).toEqual(['C3', 'C1', 'C2'])
        expect(logic.values.slackChannelsForPicker.map((c) => c.id)).toEqual(['C1', 'C3', 'C2'])
    })

    it('puts recently subscribed channels first (most recent first), then alphabetical', async () => {
        recordRecentSlackChannel(1, 'C2')
        recordRecentSlackChannel(1, 'C3')

        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()

        expect(logic.values.slackChannelsForPicker.map((c) => c.id)).toEqual(['C3', 'C2', 'C1'])
    })

    it('refreshes recency from the store each time channels load', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()
        expect(logic.values.slackChannelsForPicker.map((c) => c.id)).toEqual(['C1', 'C3', 'C2'])

        recordRecentSlackChannel(1, 'C2')
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()
        expect(logic.values.slackChannelsForPicker.map((c) => c.id)).toEqual(['C2', 'C1', 'C3'])
    })

    it('sorts channels without a name (inaccessible private channels) without throwing', () => {
        // Slack returns private channels the bot can't access with no `name`; the picker sort
        // must not blow up on them (regression: crashed the whole workflow step config panel).
        logic.actions.loadAllSlackChannelsSuccess({
            channels: [
                fixtureChannel('C1', 'alerts'),
                {
                    id: 'C_PRIV',
                    is_private: true,
                    is_ext_shared: false,
                    is_member: false,
                    is_private_without_access: true,
                },
                fixtureChannel('C2', 'general'),
            ] as SlackChannelType[],
            lastRefreshedAt: '2026-01-01T00:00:00Z',
        })

        expect(logic.values.slackChannelsForPicker.map((c) => c.id)).toEqual(['C_PRIV', 'C1', 'C2'])
    })
})
