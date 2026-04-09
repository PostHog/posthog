import '@testing-library/jest-dom'

import { EventType, RecordingEventType } from '~/types'

import { eventToActionStep, isAutocaptureWithElements } from './saveActionFromEvent'

function makeEvent(overrides: Partial<EventType> = {}): EventType {
    return {
        id: 'test-id',
        distinct_id: 'user-1',
        event: '$autocapture',
        timestamp: '2026-01-01T00:00:00Z',
        properties: { $current_url: 'https://example.com/page' },
        elements: [{ tag_name: 'button', text: 'Submit', attributes: {}, order: 0 }],
        ...overrides,
    } as EventType
}

describe('saveActionFromEvent', () => {
    describe('isAutocaptureWithElements', () => {
        it.each([
            ['autocapture with elements', makeEvent(), true],
            ['autocapture without elements', makeEvent({ elements: [] }), false],
            ['non-autocapture event', makeEvent({ event: '$pageview' }), false],
            [
                'recording event type with elements',
                { ...makeEvent(), fullyLoaded: true, playerTime: 0 } as RecordingEventType,
                true,
            ],
        ])('%s → %s', (_desc, event, expected) => {
            expect(isAutocaptureWithElements(event)).toBe(expected)
        })
    })

    describe('eventToActionStep', () => {
        it('includes url, url_matching and element-derived fields for a button event', () => {
            const step = eventToActionStep(makeEvent() as any, [])

            expect(step).toMatchObject({
                event: '$autocapture',
                url: 'https://example.com/page',
                url_matching: 'exact',
                text: 'Submit',
            })
        })

        it('applies the $event_type=submit property when present', () => {
            const event = makeEvent({
                properties: { $current_url: 'https://example.com/page', $event_type: 'submit' },
            })

            const step = eventToActionStep(event as any, [])

            expect(step.properties).toEqual([expect.objectContaining({ key: '$event_type', value: 'submit' })])
        })
    })
})
