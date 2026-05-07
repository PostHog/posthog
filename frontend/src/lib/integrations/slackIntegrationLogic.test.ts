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

    it('disables the refresh button immediately after a refresh', async () => {
        await refreshAt(dayjs(FIXED_NOW).toISOString())
        expect(logic.values.getChannelRefreshButtonDisabledReason()).not.toBe('')
    })

    it('still disables the refresh button just before the cooldown elapses', async () => {
        await refreshAt(
            dayjs(FIXED_NOW)
                .subtract(SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS - 1, 'seconds')
                .toISOString()
        )
        expect(logic.values.getChannelRefreshButtonDisabledReason()).not.toBe('')
    })

    it('enables the refresh button once the cooldown has elapsed', async () => {
        await refreshAt(
            dayjs(FIXED_NOW)
                .subtract(SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS + 1, 'seconds')
                .toISOString()
        )
        expect(logic.values.getChannelRefreshButtonDisabledReason()).toBe('')
    })
})
