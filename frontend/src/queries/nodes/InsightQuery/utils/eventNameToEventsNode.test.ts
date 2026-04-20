import { NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { eventNameToEventsNode } from './eventNameToEventsNode'

describe('eventNameToEventsNode', () => {
    it.each([
        {
            scenario: 'custom event',
            input: 'signed_up',
            expected: { kind: NodeKind.EventsNode, event: 'signed_up', name: 'signed_up' },
        },
        {
            scenario: 'PostHog built-in event',
            input: '$pageview',
            expected: { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
        },
        {
            scenario: 'screen event',
            input: '$screen',
            expected: { kind: NodeKind.EventsNode, event: '$screen', name: '$screen' },
        },
        {
            scenario: 'relative path treated as plain event name',
            input: '/dashboard/settings',
            expected: { kind: NodeKind.EventsNode, event: '/dashboard/settings', name: '/dashboard/settings' },
        },
        {
            scenario: 'https URL converted to $pageview with $current_url filter',
            input: 'https://example.com/page',
            expected: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                properties: [
                    {
                        key: '$current_url',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                        value: 'https://example.com/page',
                    },
                ],
            },
        },
        {
            scenario: 'http URL also detected as pageview',
            input: 'http://localhost:8000/test',
            expected: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                properties: [
                    {
                        key: '$current_url',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                        value: 'http://localhost:8000/test',
                    },
                ],
            },
        },
        {
            scenario: 'URL with query params preserves full URL in filter value',
            input: 'https://app.posthog.com/insights?tab=trends',
            expected: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                properties: [
                    {
                        key: '$current_url',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                        value: 'https://app.posthog.com/insights?tab=trends',
                    },
                ],
            },
        },
    ])('$scenario', ({ input, expected }) => {
        expect(eventNameToEventsNode(input)).toEqual(expected)
    })

    it('does not add properties key for non-URL events', () => {
        const result = eventNameToEventsNode('user_clicked_button')
        expect(result).not.toHaveProperty('properties')
    })
})
