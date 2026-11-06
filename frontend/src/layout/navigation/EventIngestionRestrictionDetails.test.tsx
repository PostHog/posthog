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

    it('reports an unfiltered restriction as applying to all events', () => {
        render(<EventIngestionRestrictionDetails restrictions={[restriction({})]} />)
        expect(screen.getByText('Events dropped')).toBeTruthy()
        expect(screen.getByText('Applies to all events in analytics')).toBeTruthy()
    })

    it('lists every scope filter and pipeline, and notes that filters combine', () => {
        render(
            <EventIngestionRestrictionDetails
                restrictions={[
                    restriction({
                        restriction_type: RestrictionType.SKIP_PERSON_PROCESSING,
                        distinct_ids: ['u1', 'u2'],
                        event_names: ['$pageview'],
                        pipelines: ['session_recordings', 'ai'],
                    }),
                ]}
            />
        )
        expect(screen.getByText('Person processing disabled')).toBeTruthy()
        expect(screen.getByText('Applies to some events in session recordings, AI')).toBeTruthy()
        expect(screen.getByText('Only these 2 distinct IDs:')).toBeTruthy()
        expect(screen.getByText('Only this event name:')).toBeTruthy()
        expect(screen.getByText('u1')).toBeTruthy()
        expect(screen.getByText('$pageview')).toBeTruthy()
        expect(screen.getByText('An event is affected only when it matches every filter below.')).toBeTruthy()
    })

    it('lists redirect restrictions and unknown types instead of hiding them', () => {
        render(
            <EventIngestionRestrictionDetails
                restrictions={[
                    restriction({ restriction_type: RestrictionType.REDIRECT_TO_DLQ }),
                    restriction({ restriction_type: 'some_future_type' as RestrictionType }),
                ]}
            />
        )
        expect(screen.getByText('Events held')).toBeTruthy()
        expect(screen.getByText('Restricted')).toBeTruthy()
    })

    it('truncates long value lists', () => {
        const distinctIds = Array.from({ length: 25 }, (_, i) => `user-${i}`)
        render(<EventIngestionRestrictionDetails restrictions={[restriction({ distinct_ids: distinctIds })]} />)
        expect(screen.getByText('user-19')).toBeTruthy()
        expect(screen.queryByText('user-20')).toBeNull()
        expect(screen.getByText('and 5 more')).toBeTruthy()
    })
})
