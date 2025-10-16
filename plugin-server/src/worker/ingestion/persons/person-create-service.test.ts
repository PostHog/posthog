import { DateTime } from 'luxon'

import { UUIDT } from '../../../utils/utils'
import { captureIngestionWarning } from '../utils'
import { PersonContext } from './person-context'
import { PersonCreateService } from './person-create-service'
import { createDefaultSyncMergeMode } from './person-merge-types'
import { PersonPropertiesSizeViolationError } from './repositories/person-repository'

jest.mock('../utils', () => ({
    captureIngestionWarning: jest.fn().mockResolvedValue(undefined),
}))

const mockCaptureIngestionWarning = captureIngestionWarning as jest.MockedFunction<typeof captureIngestionWarning>

describe('PersonCreateService', () => {
    let mockPersonStore: any
    let mockKafkaProducer: any
    let personContext: PersonContext
    let personCreateService: PersonCreateService
    const teamId = 123

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            queueMessages: jest.fn().mockResolvedValue(undefined),
        }

        mockPersonStore = {
            createPerson: jest.fn(),
            fetchForUpdate: jest.fn(),
        }

        const mockEvent = {
            uuid: new UUIDT().toString(),
            distinct_id: 'test-distinct-id',
            properties: {},
        }

        const mockTeam = {
            id: teamId,
        }

        personContext = new PersonContext(
            mockEvent as any,
            mockTeam as any,
            'test-distinct-id',
            DateTime.now(),
            true,
            mockKafkaProducer,
            mockPersonStore,
            0,
            createDefaultSyncMergeMode()
        )

        personCreateService = new PersonCreateService(personContext)
    })

    describe('createPerson', () => {
        const createdAt = DateTime.now()
        const properties = { name: 'John Doe' }
        const propertiesOnce = { email: 'john@example.com' }
        const isUserId = null
        const isIdentified = true
        const creatorEventUuid = new UUIDT().toString()
        const distinctIds = [{ distinctId: 'test-distinct-id', version: 0 }]

        it('should successfully create a person when store succeeds', async () => {
            const mockPerson = {
                id: '1',
                uuid: new UUIDT().toString(),
                team_id: teamId,
                properties: { ...propertiesOnce, ...properties, $creator_event_uuid: creatorEventUuid },
                created_at: createdAt,
                version: 0,
            }

            const mockResult = {
                success: true,
                person: mockPerson,
                messages: [{ topic: 'test', messages: [] }],
                created: true,
            }

            mockPersonStore.createPerson.mockResolvedValue(mockResult)

            const [person, created] = await personCreateService.createPerson(
                createdAt,
                properties,
                propertiesOnce,
                teamId,
                isUserId,
                isIdentified,
                creatorEventUuid,
                distinctIds
            )

            expect(person).toEqual(mockPerson)
            expect(created).toBe(true)
            expect(mockKafkaProducer.queueMessages).toHaveBeenCalledWith(mockResult.messages)
        })

        it('should handle PersonPropertiesSizeViolationError and log ingestion warning', async () => {
            const sizeViolationError = new PersonPropertiesSizeViolationError(
                'Person properties exceed size limit',
                teamId,
                'test-person-id',
                'test-distinct-id'
            )

            mockPersonStore.createPerson.mockRejectedValue(sizeViolationError)

            await expect(
                personCreateService.createPerson(
                    createdAt,
                    properties,
                    propertiesOnce,
                    teamId,
                    isUserId,
                    isIdentified,
                    creatorEventUuid,
                    distinctIds
                )
            ).rejects.toThrow(PersonPropertiesSizeViolationError)

            expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
                mockKafkaProducer,
                teamId,
                'person_properties_size_violation',
                {
                    personId: 'test-person-id',
                    distinctId: 'test-distinct-id',
                    eventUuid: creatorEventUuid,
                    teamId: teamId,
                    message: 'Person properties exceeds size limit and was rejected',
                }
            )
        })

        it('should handle creation conflict and fetch existing person', async () => {
            const conflictResult = {
                success: false,
                error: 'CreationConflict',
                distinctIds: ['test-distinct-id'],
            }

            const existingPerson = {
                id: '2',
                uuid: new UUIDT().toString(),
                team_id: teamId,
                properties: {},
                created_at: createdAt,
                version: 1,
            }

            mockPersonStore.createPerson.mockResolvedValue(conflictResult)
            mockPersonStore.fetchForUpdate.mockResolvedValue(existingPerson)

            const [person, created] = await personCreateService.createPerson(
                createdAt,
                properties,
                propertiesOnce,
                teamId,
                isUserId,
                isIdentified,
                creatorEventUuid,
                distinctIds
            )

            expect(person).toEqual(existingPerson)
            expect(created).toBe(false)
            expect(mockPersonStore.fetchForUpdate).toHaveBeenCalledWith(teamId, 'test-distinct-id')
        })

        it('should throw error when creation conflict occurs but person cannot be fetched', async () => {
            const conflictResult = {
                success: false,
                error: 'CreationConflict',
                distinctIds: ['test-distinct-id'],
            }

            mockPersonStore.createPerson.mockResolvedValue(conflictResult)
            mockPersonStore.fetchForUpdate.mockResolvedValue(null)

            await expect(
                personCreateService.createPerson(
                    createdAt,
                    properties,
                    propertiesOnce,
                    teamId,
                    isUserId,
                    isIdentified,
                    creatorEventUuid,
                    distinctIds
                )
            ).rejects.toThrow('Person creation failed with constraint violation, but could not fetch existing person')
        })

        it('should re-throw other errors without logging ingestion warning', async () => {
            const genericError = new Error('Some other database error')
            mockPersonStore.createPerson.mockRejectedValue(genericError)

            await expect(
                personCreateService.createPerson(
                    createdAt,
                    properties,
                    propertiesOnce,
                    teamId,
                    isUserId,
                    isIdentified,
                    creatorEventUuid,
                    distinctIds
                )
            ).rejects.toThrow('Some other database error')

            expect(mockCaptureIngestionWarning).not.toHaveBeenCalled()
        })

        it('should throw error when no distinct IDs provided', async () => {
            await expect(
                personCreateService.createPerson(
                    createdAt,
                    properties,
                    propertiesOnce,
                    teamId,
                    isUserId,
                    isIdentified,
                    creatorEventUuid,
                    [] // empty distinctIds
                )
            ).rejects.toThrow('at least 1 distinctId is required in `createPerson`')
        })
    })
})
