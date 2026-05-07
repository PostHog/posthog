import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS, slackIntegrationLogic } from './slackIntegrationLogic'

describe('slackIntegrationLogic — getChannelRefreshButtonDisabledReason', () => {
    let logic: ReturnType<typeof slackIntegrationLogic.build>
    let lastRefreshedAt: string

    beforeEach(() => {
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
    })

    const refreshAt = async (timestamp: string): Promise<void> => {
        lastRefreshedAt = timestamp
        await expectLogic(logic, () => {
            logic.actions.loadAllSlackChannels()
        }).toFinishAllListeners()
    }

    it('uses a 30 second cooldown', () => {
        expect(SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS).toBe(30)
    })

    it('disables the refresh button immediately after a refresh', async () => {
        await refreshAt(dayjs().toISOString())
        expect(logic.values.getChannelRefreshButtonDisabledReason()).not.toBe('')
    })

    it('still disables the refresh button just before the cooldown elapses', async () => {
        await refreshAt(
            dayjs()
                .subtract(SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS - 5, 'seconds')
                .toISOString()
        )
        expect(logic.values.getChannelRefreshButtonDisabledReason()).not.toBe('')
    })

    it('enables the refresh button once the cooldown has elapsed', async () => {
        await refreshAt(
            dayjs()
                .subtract(SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS + 5, 'seconds')
                .toISOString()
        )
        expect(logic.values.getChannelRefreshButtonDisabledReason()).toBe('')
    })
})
