import { cleanup, render, screen } from '@testing-library/react'

import { EventIngestionRestriction, RestrictionType } from 'lib/logic/eventIngestionRestrictionLogic'

import { EventIngestionRestrictionDetails } from './EventIngestionRestrictionDetails'

function restriction(overrides: Partial<EventIngestionRestriction>): EventIngestionRestriction {
    return {
        restriction_type: RestrictionType.DROP_EVENT_FROM_INGESTION,
        distinct_ids: [],
        session_ids: [],
        event_names: [],
        event_uuids: [],
        pipelines: ['analytics'],
        ...overrides,
    }
}

describe('EventIngestionRestrictionDetails', () => {
    afterEach(cleanup)

    it.each([
        [restriction({}), 'Events dropped', 'Applies to all events in analytics events'],
        [
            restriction({ restriction_type: RestrictionType.FORCE_OVERFLOW_FROM_INGESTION, distinct_ids: ['u1'] }),
            'Processing delayed',
            'Applies to some events in analytics events',
        ],
        [
            restriction({ restriction_type: RestrictionType.SKIP_PERSON_PROCESSING, session_ids: ['s1'] }),
            'Person processing disabled',
            'Applies to some events in analytics events',
        ],
        [
            restriction({ pipelines: ['session_recordings', 'ai'] }),
            'Events dropped',
            'Applies to all events in session recordings, AI events',
        ],
    ])('describes effect and scope (%#)', (input, expectedLabel, expectedScope) => {
        render(<EventIngestionRestrictionDetails restrictions={[input]} />)
        expect(screen.getByText(expectedLabel)).toBeTruthy()
        expect(screen.getByText(expectedScope)).toBeTruthy()
    })

    it('lists every scope filter and notes they combine', () => {
        render(
            <EventIngestionRestrictionDetails
                restrictions={[restriction({ distinct_ids: ['u1', 'u2'], event_names: ['$pageview'] })]}
            />
        )
        expect(screen.getByText('Only these 2 distinct IDs:')).toBeTruthy()
        expect(screen.getByText('Only this event name:')).toBeTruthy()
        expect(screen.getByText('u1')).toBeTruthy()
        expect(screen.getByText('$pageview')).toBeTruthy()
        expect(screen.getByText('An event is affected only when it matches every filter below.')).toBeTruthy()
    })

    it('truncates long value lists', () => {
        const distinctIds = Array.from({ length: 25 }, (_, i) => `user-${i}`)
        render(<EventIngestionRestrictionDetails restrictions={[restriction({ distinct_ids: distinctIds })]} />)
        expect(screen.getByText('user-19')).toBeTruthy()
        expect(screen.queryByText('user-20')).toBeNull()
        expect(screen.getByText('and 5 more')).toBeTruthy()
    })
})
