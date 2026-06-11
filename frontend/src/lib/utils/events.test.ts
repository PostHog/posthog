import { autoCaptureEventToDescription, eventToDescription } from 'lib/utils/events'

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
})
