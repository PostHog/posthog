import { propertyDefinitionsList } from '~/generated/core/api'

import { findMissingPropertyKeys, propertyKeysIn } from './crossProjectPropertyKeys'

jest.mock('~/generated/core/api', () => ({ __esModule: true, propertyDefinitionsList: jest.fn() }))

const mockedList = propertyDefinitionsList as jest.Mock

describe('crossProjectPropertyKeys', () => {
    beforeEach(() => {
        mockedList.mockReset()
    })

    describe('propertyKeysIn', () => {
        it('collects each key once per type', () => {
            expect(
                propertyKeysIn([
                    { key: 'browser', type: 'event' },
                    { key: 'browser', type: 'event' },
                    { key: 'plan', type: 'person' },
                ])
            ).toEqual([
                { key: 'browser', type: 'event' },
                { key: 'plan', type: 'person' },
            ])
        })

        it('leaves out filter types the property definitions endpoint cannot answer for', () => {
            expect(propertyKeysIn([{ key: 'distinct_id', type: 'event_metadata' }, { key: 'plan' }])).toEqual([])
        })

        it('returns nothing for filters that carry no key', () => {
            expect(propertyKeysIn([{ value: 'x' }, null, 'nonsense'])).toEqual([])
            expect(propertyKeysIn(undefined)).toEqual([])
        })
    })

    describe('findMissingPropertyKeys', () => {
        it('reports a key the project has never recorded', async () => {
            mockedList.mockResolvedValue({ results: [] })

            expect(await findMissingPropertyKeys([7], [{ key: 'plan', type: 'event' }])).toEqual({ 7: ['plan'] })
        })

        it('asks for a person property as a person property, not as the default event type', async () => {
            mockedList.mockResolvedValue({ results: [{ name: 'email' }] })

            expect(await findMissingPropertyKeys([7], [{ key: 'email', type: 'person' }])).toEqual({})
            expect(mockedList).toHaveBeenCalledWith('7', expect.objectContaining({ type: 'person' }))
        })

        it('does not report a key the project has, even when the search returns near matches', async () => {
            mockedList.mockResolvedValue({ results: [{ name: 'plan_tier' }, { name: 'plan' }] })

            expect(await findMissingPropertyKeys([7], [{ key: 'plan', type: 'event' }])).toEqual({})
        })

        it('treats an unreachable project as no answer rather than a missing key', async () => {
            // A 403 means the reader cannot see the project, not that the key is absent. Reporting
            // it as missing would warn about a tile whose data is fine.
            mockedList.mockRejectedValue({ status: 403 })

            expect(await findMissingPropertyKeys([7], [{ key: 'plan', type: 'event' }])).toEqual({})
        })

        it('asks nothing when there are no keys to check', async () => {
            expect(await findMissingPropertyKeys([7, 8], [])).toEqual({})
            expect(mockedList).not.toHaveBeenCalled()
        })
    })
})
