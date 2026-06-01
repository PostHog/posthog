import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SlackChannelType } from '~/types'

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
