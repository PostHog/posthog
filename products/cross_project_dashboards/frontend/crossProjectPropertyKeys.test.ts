import api from 'lib/api'

import { findMissingPropertyKeys, propertyKeysIn } from './crossProjectPropertyKeys'

jest.mock('lib/api', () => ({ __esModule: true, default: { get: jest.fn() } }))

const mockedGet = api.get as jest.Mock

describe('crossProjectPropertyKeys', () => {
    beforeEach(() => {
        mockedGet.mockReset()
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
            mockedGet.mockResolvedValue({ results: [] })

            expect(await findMissingPropertyKeys([7], [{ key: 'plan', type: 'event' }])).toEqual({ 7: ['plan'] })
        })

        it('asks for a person property as a person property, not as the default event type', async () => {
            mockedGet.mockResolvedValue({ results: [{ name: 'email' }] })

            expect(await findMissingPropertyKeys([7], [{ key: 'email', type: 'person' }])).toEqual({})
            expect(mockedGet.mock.calls[0][0]).toContain('type=person')
        })

        it('does not report a key the project has, even when the search returns near matches', async () => {
            mockedGet.mockResolvedValue({ results: [{ name: 'plan_tier' }, { name: 'plan' }] })

            expect(await findMissingPropertyKeys([7], [{ key: 'plan', type: 'event' }])).toEqual({})
        })

        it('treats an unreachable project as no answer rather than a missing key', async () => {
            // A 403 means the reader cannot see the project, not that the key is absent. Reporting
            // it as missing would warn about a tile whose data is fine.
            mockedGet.mockRejectedValue({ status: 403 })

            expect(await findMissingPropertyKeys([7], [{ key: 'plan', type: 'event' }])).toEqual({})
        })

        it('asks nothing when there are no keys to check', async () => {
            expect(await findMissingPropertyKeys([7, 8], [])).toEqual({})
            expect(mockedGet).not.toHaveBeenCalled()
        })
    })
})
