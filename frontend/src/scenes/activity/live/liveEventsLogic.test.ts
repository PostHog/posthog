import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { LiveEvent } from '~/types'

import { liveEventsLogic } from './liveEventsLogic'

function makeLiveEvent(currentUrl?: string): LiveEvent {
    return {
        uuid: 'abc',
        event: '$pageview',
        properties: currentUrl !== undefined ? { $current_url: currentUrl } : {},
        timestamp: '2026-01-01T00:00:00Z',
        team_id: 1,
        distinct_id: 'user-1',
        created_at: '2026-01-01T00:00:00Z',
    }
}

describe('liveEventsLogic', () => {
    let logic: ReturnType<typeof liveEventsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = liveEventsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('addEvents host extraction', () => {
        it('records the host for a valid $current_url', async () => {
            await expectLogic(logic, () => {
                logic.actions.addEvents([makeLiveEvent('https://app.posthog.com/insights')])
            }).toMatchValues({
                eventHosts: ['https://app.posthog.com'],
            })
        })

        it.each([
            ['malformed URL', 'not a url'],
            ['empty host', 'https://'],
        ])('does not throw and records no host for %s', async (_label, currentUrl) => {
            await expectLogic(logic, () => {
                logic.actions.addEvents([makeLiveEvent(currentUrl)])
            }).toMatchValues({
                eventHosts: [],
            })
        })

        it('records no host when $current_url is missing', async () => {
            await expectLogic(logic, () => {
                logic.actions.addEvents([makeLiveEvent()])
            }).toMatchValues({
                eventHosts: [],
            })
        })
    })
})
