import { PluginEvent, PluginInput, PluginMeta } from '@posthog/plugin-scaffold'

import { processEvent } from './index'

/**
 * Given a url, construct a page view event.
 *
 * @param $current_url The current url of the page view
 * @returns A new PostHog page view event
 */
function buildEventWithName(eventName: string): PluginEvent {
    const event: PluginEvent = {
        distinct_id: 'distinct_id',
        ip: '1.2.3.4',
        site_url: 'test.com',
        team_id: 0,
        now: '2022-06-17T20:21:31.778000+00:00',
        event: eventName,
        uuid: '01817354-06bb-0000-d31c-2c4eed374100',
    }

    return event
}

function getMeta(): PluginMeta<PluginInput> {
    return {} as unknown as PluginMeta<PluginInput>
}

describe('ph-shotgun-processevent-app', () => {
    it('should rename the event if in the list', () => {
        const sourceEvent = buildEventWithName('Community Management Dashboard Displayed')

        const processedEvent = processEvent(sourceEvent, getMeta())

        expect(processedEvent?.event).toEqual('Analytics Community Overview Tab Displayed')
    })

    it('should rename the event if in the list', () => {
        const sourceEvent = buildEventWithName('Community Management Insights Overview Tab Displayed')

        const processedEvent = processEvent(sourceEvent, getMeta())

        expect(processedEvent?.event).toEqual('Analytics Community Overview Tab Displayed')
    })

    it('should rename the event if in the list', () => {
        const sourceEvent = buildEventWithName('Community Management Contacts Imported')

        const processedEvent = processEvent(sourceEvent, getMeta())

        expect(processedEvent?.event).toEqual('Marketing Contacts Imported')
    })

    it('should rename the event if in the list', () => {
        const sourceEvent = buildEventWithName('Marketing Organizer Page Tab Displayed')

        const processedEvent = processEvent(sourceEvent, getMeta())

        expect(processedEvent?.event).toEqual('My Page Tab Displayed')
    })

    it('should rename the event if in the list', () => {
        const sourceEvent = buildEventWithName('Settings')

        const processedEvent = processEvent(sourceEvent, getMeta())

        expect(processedEvent?.event).toEqual('Profile Screen Settings Tapped')
    })

    it('should rename the event if in the list', () => {
        const sourceEvent = buildEventWithName('Log Out')

        const processedEvent = processEvent(sourceEvent, getMeta())

        expect(processedEvent?.event).toEqual('Logged Out')
    })

    it('should rename the event if in the list', () => {
        const sourceEvent = buildEventWithName('Music Library Sync Completed')

        const processedEvent = processEvent(sourceEvent, getMeta())

        expect(processedEvent?.event).toEqual('Music Library Sync Completed')
    })

    it('should rename the event if in the list', () => {
        const sourceEvent = buildEventWithName('Non Existing Event')

        const processedEvent = processEvent(sourceEvent, getMeta())

        expect(processedEvent?.event).toEqual('Non Existing Event')
    })

    it('should rename the event if in the list', () => {
        const sourceEvent = buildEventWithName('KYB Completed')

        const processedEvent = processEvent(sourceEvent, getMeta())

        expect(processedEvent?.event).toEqual('KYB Completed')
    })

    it('should rename the event if in the list', () => {
        const sourceEvent = buildEventWithName('Reward Score Explanation Sheet Displayed')

        const processedEvent = processEvent(sourceEvent, getMeta())

        expect(processedEvent?.event).toEqual('Reward Score Explanation Sheet Displayed')
    })
})
