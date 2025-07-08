import { PersonsManagerService } from './persons-manager.service'

describe('PersonsManagerService', () => {
    let personsManager: PersonsManagerService
    let mockHub: any
    let fetchPersonMock: jest.Mock

    const TEAM_ID = 1
    const DISTINCT_ID = 'abc123'
    const PERSON_DATA = { id: DISTINCT_ID, properties: { foo: 'bar' } }

    beforeEach(() => {
        fetchPersonMock = jest.fn()
        mockHub = {
            db: {
                fetchPerson: fetchPersonMock,
            },
        }
        personsManager = new PersonsManagerService(mockHub)
    })

    it('should load person properties and cache them', async () => {
        fetchPersonMock.mockResolvedValue(PERSON_DATA)
        const person = await personsManager.getPerson(TEAM_ID, DISTINCT_ID)
        expect(person).toEqual(PERSON_DATA)
        // Should be cached
        expect(personsManager['personsCache'].get(DISTINCT_ID)).toEqual(PERSON_DATA)
    })

    it('should return cached properties without querying the database', async () => {
        personsManager['personsCache'].set(DISTINCT_ID, PERSON_DATA)
        const person = await personsManager.getPerson(TEAM_ID, DISTINCT_ID)
        expect(person).toEqual(PERSON_DATA)
        expect(fetchPersonMock).not.toHaveBeenCalled()
    })

    it('fetches person properties if not cached', async () => {
        fetchPersonMock.mockResolvedValue(PERSON_DATA)
        const result = await personsManager.getPerson(TEAM_ID, DISTINCT_ID)
        expect(result).toEqual(PERSON_DATA)
        expect(fetchPersonMock).toHaveBeenCalledWith(TEAM_ID, DISTINCT_ID)
    })

    it('throws if person is not found', async () => {
        fetchPersonMock.mockResolvedValue(null)
        await expect(personsManager.getPerson(TEAM_ID, DISTINCT_ID)).rejects.toThrow(
            `Person not found for team ${TEAM_ID} and distinctId ${DISTINCT_ID}`
        )
    })

    it('returns empty object if person object has no properties', async () => {
        fetchPersonMock.mockResolvedValue({ id: DISTINCT_ID })
        const result = await personsManager.getPerson(TEAM_ID, DISTINCT_ID)
        expect(result).toEqual({ id: DISTINCT_ID, properties: {} })
    })
})
