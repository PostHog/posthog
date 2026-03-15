import { DateTime } from 'luxon'

import { ISOTimestamp, Person, PreIngestionEvent, ProjectId } from '../../types'
import { createEvent, getElementsChain } from './create-event'

describe('createEvent', () => {
    const mockPreparedEvent: PreIngestionEvent = {
        eventUuid: 'event-uuid-123',
        event: '$exception',
        teamId: 1,
        projectId: 1 as ProjectId,
        distinctId: 'distinct-id-456',
        properties: { $exception_list: [{ type: 'Error', value: 'Test' }] },
        timestamp: '2024-01-01T00:00:00.000Z' as ISOTimestamp,
    }

    const mockPerson: Person = {
        team_id: 1,
        uuid: 'person-uuid-789',
        properties: { email: 'test@example.com' },
        created_at: DateTime.fromISO('2024-01-01T00:00:00.000Z'),
    }

    describe('with person', () => {
        it('uses person uuid as person_id', () => {
            const result = createEvent(mockPreparedEvent, mockPerson, true, false, null)

            expect(result.person_id).toBe('person-uuid-789')
        })

        it('includes person properties when processPerson=true', () => {
            const result = createEvent(mockPreparedEvent, mockPerson, true, false, null)

            expect(result.person_properties).toEqual({ email: 'test@example.com' })
        })

        it('uses person created_at', () => {
            const result = createEvent(mockPreparedEvent, mockPerson, true, false, null)

            expect(result.person_created_at).toEqual(mockPerson.created_at)
        })

        it('sets person_mode to force_upgrade when person has force_upgrade=true', () => {
            const personWithForceUpgrade = { ...mockPerson, force_upgrade: true }

            const result = createEvent(mockPreparedEvent, personWithForceUpgrade, true, false, null)

            expect(result.person_mode).toBe('force_upgrade')
        })
    })

    describe('without person (undefined)', () => {
        it('generates deterministic person_id from distinct_id', () => {
            const result = createEvent(mockPreparedEvent, undefined, true, false, null)

            expect(result.person_id).toBeDefined()
            expect(result.person_id).toMatch(/^[0-9a-f-]{36}$/)

            // Should be deterministic - same distinct_id produces same person_id
            const result2 = createEvent(mockPreparedEvent, undefined, true, false, null)
            expect(result2.person_id).toBe(result.person_id)
        })

        it('returns empty person_properties when processPerson=true', () => {
            const result = createEvent(mockPreparedEvent, undefined, true, false, null)

            expect(result.person_properties).toEqual({})
        })

        it('sets person_created_at to null', () => {
            const result = createEvent(mockPreparedEvent, undefined, true, false, null)

            expect(result.person_created_at).toBeNull()
        })

        it('sets person_mode to full (not force_upgrade)', () => {
            const result = createEvent(mockPreparedEvent, undefined, true, false, null)

            expect(result.person_mode).toBe('full')
        })

        it('sets person_mode to propertyless when processPerson=false', () => {
            const result = createEvent(mockPreparedEvent, undefined, false, false, null)

            expect(result.person_mode).toBe('propertyless')
        })
    })
})

describe('getElementsChain', () => {
    it('returns empty string when neither $elements nor $elements_chain is present', () => {
        const properties = { foo: 'bar' }
        const result = getElementsChain(properties)
        expect(result).toBe('')
    })

    it('returns $elements_chain directly and removes it from properties', () => {
        const chain = 'div:nth-child="1"nth-of-type="2"'
        const properties = { $elements_chain: chain, other: 'value' }

        const result = getElementsChain(properties)

        expect(result).toBe(chain)
        expect(properties).not.toHaveProperty('$elements_chain')
        expect(properties).toHaveProperty('other', 'value')
    })

    it('converts $elements array to chain string and removes it from properties', () => {
        const properties = {
            $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: 'text' }],
            other: 'value',
        }

        const result = getElementsChain(properties)

        expect(result).not.toBe('')
        expect(typeof result).toBe('string')
        expect(properties).not.toHaveProperty('$elements')
        expect(properties).toHaveProperty('other', 'value')
    })

    it('prefers $elements_chain over $elements when both are present, and removes both', () => {
        const chain = 'span:nth-child="3"nth-of-type="1"'
        const properties = {
            $elements_chain: chain,
            $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: 'text' }],
        }

        const result = getElementsChain(properties)

        expect(result).toBe(chain)
        expect(properties).not.toHaveProperty('$elements_chain')
        expect(properties).not.toHaveProperty('$elements')
    })

    it('returns empty string and removes both keys when $elements is an empty array', () => {
        const properties = { $elements: [], $elements_chain: '' }

        const result = getElementsChain(properties)

        expect(result).toBe('')
        expect(properties).not.toHaveProperty('$elements_chain')
        expect(properties).not.toHaveProperty('$elements')
    })
})
