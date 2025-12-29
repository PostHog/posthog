import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'
import { processEvent } from './index'

/**
 * Given a url, construct a page view event.
 *
 * @param $current_url The current url of the page view
 * @returns A new PostHog page view event
 */
function buildPageViewEvent($current_url: string): PluginEvent {
    const event: PluginEvent = {
        properties: { $current_url },
        distinct_id: 'distinct_id',
        ip: '1.2.3.4',
        site_url: 'test.com',
        team_id: 0,
        now: '2022-06-17T20:21:31.778000+00:00',
        event: '$pageview',
        uuid: '01817354-06bb-0000-d31c-2c4eed374100',
    }

    return event
}

function buildEventWithoutCurrentUrl(): PluginEvent {
    const event: PluginEvent = {
        properties: {},
        distinct_id: 'distinct_id',
        ip: '1.2.3.4',
        site_url: 'test.com',
        team_id: 0,
        now: '2022-06-17T20:21:31.778000+00:00',
        event: '$identify',
        uuid: '01817354-06bb-0000-d31c-2c4eed374100',
    }

    return event
}

const meta = {
    logger: {
        debug: jest.fn(),
    },
} as unknown as LegacyTransformationPluginMeta

describe('processEvent', () => {
    it("shouldn't change a url that's already lowercase", () => {
        const sourceEvent = buildPageViewEvent('http://www.google.com/test')

        const processedEvent = processEvent(sourceEvent, meta)

        expect(processedEvent?.properties?.$current_url).toEqual('http://www.google.com/test')
    })

    it('should convert the current_url to lowercase', () => {
        const sourceEvent = buildPageViewEvent('http://www.GoOGle.com/WhatAreYouThinking')

        const processedEvent = processEvent(sourceEvent, meta)

        expect(processedEvent?.properties?.$current_url).toEqual('http://www.google.com/whatareyouthinking')
    })

    it('should remove the trailing slash from the current_url', () => {
        const sourceEvent = buildPageViewEvent('http://www.google.com/this_is_a_test/')

        const processedEvent = processEvent(sourceEvent, meta)

        expect(processedEvent?.properties?.$current_url).toEqual('http://www.google.com/this_is_a_test')
    })

    it("should preserve the trailing slash if it's the only character in the path", () => {
        const sourceEvent = buildPageViewEvent('http://www.google.com/')

        const processedEvent = processEvent(sourceEvent, meta)

        expect(processedEvent?.properties?.$current_url).toEqual('http://www.google.com/')
    })

    it('should preserve trailing id anchors', () => {
        const sourceEvent = buildPageViewEvent('http://www.google.com/this_is_a_test#id_anchor')

        const processedEvent = processEvent(sourceEvent, meta)

        expect(processedEvent?.properties?.$current_url).toEqual('http://www.google.com/this_is_a_test#id_anchor')
    })

    it('should preserve trailing anchors but drop trailing slashes', () => {
        const sourceEvent = buildPageViewEvent('http://www.google.com/this_is_a_test_with_trailing_slash/#id_anchor')

        const processedEvent = processEvent(sourceEvent, meta)

        expect(processedEvent?.properties?.$current_url).toEqual(
            'http://www.google.com/this_is_a_test_with_trailing_slash#id_anchor'
        )
    })

    it("shouldn't modify events that don't have a $current_url set", () => {
        const sourceEvent = buildEventWithoutCurrentUrl()

        const processedEvent = processEvent(sourceEvent, meta)

        expect(processedEvent).toEqual(sourceEvent)
        expect(processedEvent?.properties).toEqual(sourceEvent.properties)
        expect(processedEvent?.properties?.$current_url).toBeUndefined()
    })

    it('should raise an error if the $current_url is an invalid url', () => {
        const sourceEvent = buildPageViewEvent('invalid url')

        expect(() => processEvent(sourceEvent, meta)).toThrow(`Unable to normalize invalid URL: "invalid url"`)
    })

    it('should log the normalized_url for debugging', () => {
        const sourceEvent = buildPageViewEvent('http://www.GoOGle.com/WhatAreYouThinking')
        processEvent(sourceEvent, meta)

        expect(meta.logger.debug).toHaveBeenCalledWith(
            'event.$current_url: "http://www.GoOGle.com/WhatAreYouThinking" normalized to "http://www.google.com/whatareyouthinking"'
        )
    })
})
