import { cleanup, render, screen } from '@testing-library/react'

import { RestrictionType } from 'lib/logic/eventIngestionRestrictionLogic'

import { EventIngestionRestrictionDetails } from './EventIngestionRestrictionDetails'

describe('EventIngestionRestrictionDetails', () => {
    afterEach(cleanup)

    it.each([
        [RestrictionType.DROP_EVENT_FROM_INGESTION, null, 'Events dropped', 'Applies to all events in this project'],
        [RestrictionType.DROP_EVENT_FROM_INGESTION, [], 'Events dropped', 'Applies to all events in this project'],
        [RestrictionType.FORCE_OVERFLOW_FROM_INGESTION, ['u1'], 'Processing delayed', 'Applies to 1 distinct ID'],
        [
            RestrictionType.SKIP_PERSON_PROCESSING,
            ['u1', 'u2'],
            'Person processing disabled',
            'Applies to 2 distinct IDs',
        ],
    ])('explains %s scoped to %j', (restrictionType, distinctIds, expectedLabel, expectedScope) => {
        render(
            <EventIngestionRestrictionDetails
                restrictions={[{ restriction_type: restrictionType, distinct_ids: distinctIds }]}
            />
        )
        expect(screen.getByText(expectedLabel)).toBeTruthy()
        expect(screen.getByText(expectedScope)).toBeTruthy()
        for (const distinctId of distinctIds ?? []) {
            expect(screen.getByText(distinctId)).toBeTruthy()
        }
    })

    it('truncates long distinct ID lists', () => {
        const distinctIds = Array.from({ length: 25 }, (_, i) => `user-${i}`)
        render(
            <EventIngestionRestrictionDetails
                restrictions={[
                    { restriction_type: RestrictionType.DROP_EVENT_FROM_INGESTION, distinct_ids: distinctIds },
                ]}
            />
        )
        expect(screen.getByText('user-19')).toBeTruthy()
        expect(screen.queryByText('user-20')).toBeNull()
        expect(screen.getByText('and 5 more')).toBeTruthy()
    })
})
