import {
    autoCaptureEventToDescription,
    distinctPrimaryPropertiesForEvents,
    eventToDescription,
    getEventsWithPrimaryProperty,
    getPrimaryPropertyForEvent,
    hasTaxonomyPrimaryProperty,
} from 'lib/utils/events'

import { ElementType, EventType } from '~/types'

describe('events utils', () => {
    describe('eventToName()', () => {
        const baseEvent = {
            elements: [],
            event: '',
            properties: {},
            person: {},
        } as any as EventType

        it('handles page events as expected', () => {
            expect(
                eventToDescription({ ...baseEvent, event: '$pageview', properties: { $pathname: '/hello' } })
            ).toEqual('/hello')
            expect(
                eventToDescription({ ...baseEvent, event: '$pageleave', properties: { $pathname: '/bye' } })
            ).toEqual('/bye')
        })

        it('handles screen events using $screen_name', () => {
            expect(
                eventToDescription({ ...baseEvent, event: '$screen', properties: { $screen_name: 'CartScreen' } })
            ).toEqual('CartScreen')
        })

        it('falls back to event name when the primary property is missing', () => {
            // Old behaviour fell back to $current_url for $pageview without $pathname; the new
            // single-property contract returns the event name instead so the change is explicit
            // and consistent with $screen / $feature_flag_called.
            expect(
                eventToDescription({
                    ...baseEvent,
                    event: '$pageview',
                    properties: { $current_url: 'https://example.com/' },
                })
            ).toEqual('$pageview')
        })

        it('handles no text autocapture as expected', () => {
            expect(
                eventToDescription({
                    ...baseEvent,
                    event: '$autocapture',
                    properties: { $event_type: 'click' },
                })
            ).toEqual('clicked element')
        })

        it('handles long form autocapture as expected', () => {
            expect(
                eventToDescription({
                    ...baseEvent,
                    event: '$autocapture',
                    properties: { $event_type: 'click' },
                    elements: [{ tag_name: 'button', text: 'hello' } as ElementType],
                })
            ).toEqual('clicked button with text "hello"')
        })

        it('handles short form autocapture as expected', () => {
            expect(
                eventToDescription(
                    {
                        ...baseEvent,
                        event: '$autocapture',
                        properties: { $event_type: 'click' },
                        elements: [{ tag_name: 'button', text: 'hello' } as ElementType],
                    },
                    true
                )
            ).toEqual('clicked "hello"')
        })

        it.each([
            ['with a flag key', { $feature_flag: 'my-flag-key' }, 'my-flag-key'],
            ['without the flag key property', {}, '$feature_flag_called'],
        ])('handles feature flag called events %s', (_, properties, expected) => {
            expect(
                eventToDescription({
                    ...baseEvent,
                    event: '$feature_flag_called',
                    properties,
                })
            ).toEqual(expected)
        })

        it('handles unknown event/action', () => {
            expect(
                eventToDescription({
                    ...baseEvent,
                    event: 'custom event/action',
                })
            ).toEqual('custom event/action')
        })
    })

    describe('autoCaptureEventToDescription()', () => {
        const baseEvent = {
            elements: [],
            event: '$autocapture',
            properties: { $event_type: 'click' },
            person: {},
        } as any as EventType

        it('handles regular text by adding quotes', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    properties: {
                        ...baseEvent.properties,
                        $el_text: 'Analyzing Characters with',
                    },
                })
            ).toEqual('clicked element with text "Analyzing Characters with"')
        })

        it('prioritizes $el_text from properties over text in elements array', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    properties: {
                        ...baseEvent.properties,
                        $el_text: 'Text from properties',
                    },
                    elements: [{ tag_name: 'button', text: 'Text from elements' } as ElementType],
                })
            ).toEqual('clicked button with text "Text from properties"')
        })

        it('handles text with double quotes without adding additional quotes', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    properties: {
                        ...baseEvent.properties,
                        $el_text: 'Unit Skills Assessment 1: "',
                    },
                })
            ).toEqual('clicked element with text "Unit Skills Assessment 1: ""')
        })

        it('handles text with single quotes without adding additional quotes', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    properties: {
                        ...baseEvent.properties,
                        $el_text: "Reading Lesson: '",
                    },
                })
            ).toEqual('clicked element with text "Reading Lesson: \'"')
        })

        it('handles longer text with single quotes without adding additional quotes', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    properties: {
                        ...baseEvent.properties,
                        $el_text: "A Sense of Wonder: An Introduction to Science Fiction'",
                    },
                })
            ).toEqual('clicked element with text "A Sense of Wonder: An Introduction to Science Fiction\'"')
        })

        it('handles text in elements array', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    elements: [{ tag_name: 'button', text: 'hello world' } as ElementType],
                })
            ).toEqual('clicked button with text "hello world"')
        })

        it('handles text with quotes in elements array', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    elements: [{ tag_name: 'button', text: 'hello "world"' } as ElementType],
                })
            ).toEqual('clicked button with text "hello "world""')
        })

        it('handles aria-label attributes', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    elements: [
                        {
                            tag_name: 'button',
                            attributes: { 'attr__aria-label': 'Close dialog' },
                        } as ElementType,
                    ],
                })
            ).toEqual('clicked button with aria label "Close dialog"')
        })

        it('handles aria-label attributes with quotes', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    elements: [
                        {
                            tag_name: 'button',
                            attributes: { 'attr__aria-label': 'Close "main" dialog' },
                        } as ElementType,
                    ],
                })
            ).toEqual('clicked button with aria label "Close "main" dialog"')
        })
    })

    describe('getPrimaryPropertyForEvent', () => {
        it.each([
            ['$pageview', '$pathname'],
            ['$pageleave', '$pathname'],
            ['$screen', '$screen_name'],
            ['$feature_flag_called', '$feature_flag'],
            ['$exception', '$exception_type'],
            ['$ai_generation', '$ai_model'],
            ['$ai_trace', '$ai_span_name'],
            ['$ai_span', '$ai_span_name'],
            ['$ai_metric', '$ai_metric_name'],
            ['$ai_evaluation', '$ai_evaluation_name'],
            ['$csp_violation', '$csp_violated_directive'],
            ['$mcp_tool_call', '$mcp_tool_name'],
            ['$mcp_resource_read', '$mcp_resource_name'],
            ['$mcp_prompt_get', '$mcp_resource_name'],
            ['Deep link opened', 'url'],
        ])('returns the core taxonomy default for %s', (eventName, expected) => {
            expect(getPrimaryPropertyForEvent(eventName)).toBe(expected)
        })

        it('returns null for events with no taxonomy default and no override', () => {
            expect(getPrimaryPropertyForEvent('$autocapture')).toBeNull()
            expect(getPrimaryPropertyForEvent('some_custom_event')).toBeNull()
        })

        it('returns null for missing event names', () => {
            expect(getPrimaryPropertyForEvent(null)).toBeNull()
            expect(getPrimaryPropertyForEvent(undefined)).toBeNull()
            expect(getPrimaryPropertyForEvent('')).toBeNull()
        })

        it('ignores team-configured overrides for events that have a taxonomy default', () => {
            // Taxonomy is immutable — users can only set primary properties for events
            // without a fixed taxonomy entry.
            expect(getPrimaryPropertyForEvent('$pageview', { $pageview: '$current_url' })).toBe('$pathname')
            expect(getPrimaryPropertyForEvent('$screen', { $screen: 'my_custom_prop' })).toBe('$screen_name')
        })

        it('uses the team-configured override for custom events with no taxonomy default', () => {
            expect(getPrimaryPropertyForEvent('order_placed', { order_placed: 'order_id' })).toBe('order_id')
        })

        it('returns null when no override and no taxonomy default', () => {
            expect(getPrimaryPropertyForEvent('order_placed', { other_event: 'x' })).toBeNull()
        })
    })

    describe('getEventsWithPrimaryProperty', () => {
        it('returns events that have a taxonomy default', () => {
            const events = [
                { event: '$pageview', id: 1 },
                { event: '$autocapture', id: 2 },
                { event: '$screen', id: 3 },
            ]
            expect(getEventsWithPrimaryProperty(events)).toEqual([
                { event: '$pageview', id: 1 },
                { event: '$screen', id: 3 },
            ])
        })

        it('returns events that have a team override (no taxonomy default)', () => {
            const events = [
                { event: 'order_placed', id: 1 },
                { event: 'just_viewed', id: 2 },
            ]
            expect(getEventsWithPrimaryProperty(events, { order_placed: 'order_id' })).toEqual([
                { event: 'order_placed', id: 1 },
            ])
        })

        it('does not include events whose only override is on a taxonomy-fixed event', () => {
            // Taxonomy wins, so an attempted override on $pageview is moot — but the event is still
            // included because the taxonomy default already counts as a primary property.
            const events = [{ event: '$pageview', id: 1 }]
            expect(getEventsWithPrimaryProperty(events, { $pageview: '$current_url' })).toEqual(events)
        })

        it('returns an empty list when nothing has a primary property', () => {
            const events = [
                { event: '$autocapture', id: 1 },
                { event: 'arbitrary_custom', id: 2 },
            ]
            expect(getEventsWithPrimaryProperty(events)).toEqual([])
        })
    })

    describe('distinctPrimaryPropertiesForEvents', () => {
        it('returns the distinct taxonomy defaults for a list of events', () => {
            expect(distinctPrimaryPropertiesForEvents(['$pageview', '$pageleave', '$screen'])).toEqual([
                '$pathname',
                '$screen_name',
            ])
        })

        it('includes team overrides for events with no taxonomy default', () => {
            expect(
                distinctPrimaryPropertiesForEvents(['$pageview', 'order_placed'], { order_placed: 'order_id' })
            ).toEqual(['$pathname', 'order_id'])
        })

        it('returns an empty list for no event names', () => {
            expect(distinctPrimaryPropertiesForEvents([])).toEqual([])
        })

        it('returns an empty list when nothing has a primary property', () => {
            expect(distinctPrimaryPropertiesForEvents(['$autocapture', 'arbitrary_custom'])).toEqual([])
        })
    })

    describe('hasTaxonomyPrimaryProperty', () => {
        it('is true for built-in events that have a primary property', () => {
            expect(hasTaxonomyPrimaryProperty('$pageview')).toBe(true)
            expect(hasTaxonomyPrimaryProperty('$pageleave')).toBe(true)
            expect(hasTaxonomyPrimaryProperty('$screen')).toBe(true)
            expect(hasTaxonomyPrimaryProperty('$feature_flag_called')).toBe(true)
        })

        it('is false for events with no taxonomy primary property', () => {
            expect(hasTaxonomyPrimaryProperty('$autocapture')).toBe(false)
            expect(hasTaxonomyPrimaryProperty('order_placed')).toBe(false)
            expect(hasTaxonomyPrimaryProperty(null)).toBe(false)
            expect(hasTaxonomyPrimaryProperty(undefined)).toBe(false)
            expect(hasTaxonomyPrimaryProperty('')).toBe(false)
        })
    })
})
