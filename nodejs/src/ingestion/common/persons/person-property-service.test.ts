import { DateTime } from 'luxon'

import { PersonPropertiesSizeViolationError } from '~/common/persons/repositories/person-repository'
import { UUIDT } from '~/common/utils/utils'
import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'

import { PersonContext } from './person-context'
import { createDefaultSyncMergeMode } from './person-merge-types'
import { PersonPropertyService } from './person-property-service'

jest.mock('~/ingestion/common/ingestion-warnings', () => ({
    emitIngestionWarning: jest.fn().mockResolvedValue(undefined),
}))

const mockEmitIngestionWarning = emitIngestionWarning as jest.MockedFunction<typeof emitIngestionWarning>

describe('PersonPropertyService', () => {
    const teamId = 123

    function buildService(distinctId: string, store: any): PersonPropertyService {
        const context = new PersonContext(
            { uuid: new UUIDT().toString(), distinct_id: distinctId, properties: {} } as any,
            { id: teamId } as any,
            distinctId,
            DateTime.now(),
            true,
            { produce: jest.fn().mockResolvedValue(undefined) } as any,
            store,
            0,
            createDefaultSyncMergeMode(),
            false,
            false
        )
        return new PersonPropertyService(context)
    }

    function storeCreatingNewPerson(overrides: Partial<Record<string, any>> = {}): any {
        return {
            fetchForUpdate: jest.fn().mockResolvedValue(null),
            fetchForChecking: jest.fn().mockResolvedValue(null),
            createPerson: jest.fn().mockResolvedValue({
                success: true,
                created: true,
                messages: [],
                person: { uuid: new UUIDT().toString(), properties: {} },
            }),
            ...overrides,
        }
    }

    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('warns when a fresh mixed-case distinct id collides with an existing lowercased twin', async () => {
        const twinUuid = new UUIDT().toString()
        const store = storeCreatingNewPerson({
            fetchForChecking: jest.fn().mockResolvedValue({ uuid: twinUuid, properties: {} }),
        })
        const service = buildService('Intaldarryl@gmail.com', store)

        const [, kafkaAck] = await service.updateProperties()
        await kafkaAck

        expect(store.fetchForChecking).toHaveBeenCalledWith(teamId, 'intaldarryl@gmail.com')
        expect(mockEmitIngestionWarning).toHaveBeenCalledWith(
            expect.anything(),
            teamId,
            expect.objectContaining({
                type: 'distinct_id_case_collision',
                details: expect.objectContaining({
                    distinctId: 'Intaldarryl@gmail.com',
                    existingDistinctId: 'intaldarryl@gmail.com',
                    personId: twinUuid,
                }),
                key: 'Intaldarryl@gmail.com',
            })
        )
    })

    it('does not warn about a case collision when person creation fails', async () => {
        const store = storeCreatingNewPerson({
            fetchForChecking: jest.fn().mockResolvedValue({ uuid: new UUIDT().toString(), properties: {} }),
            createPerson: jest.fn().mockRejectedValue(new PersonPropertiesSizeViolationError('too large', teamId)),
        })
        const service = buildService('Intaldarryl@gmail.com', store)

        await expect(service.updateProperties()).rejects.toThrow(PersonPropertiesSizeViolationError)

        expect(mockEmitIngestionWarning).not.toHaveBeenCalledWith(
            expect.anything(),
            teamId,
            expect.objectContaining({ type: 'distinct_id_case_collision' })
        )
    })

    it('continues person creation when the twin lookup fails', async () => {
        const createdPerson = { uuid: new UUIDT().toString(), properties: {} }
        const store = storeCreatingNewPerson({
            fetchForChecking: jest.fn().mockRejectedValue(new Error('persons read replica unavailable')),
            createPerson: jest.fn().mockResolvedValue({
                success: true,
                created: true,
                messages: [],
                person: createdPerson,
            }),
        })
        const service = buildService('Intaldarryl@gmail.com', store)

        const [person, kafkaAck] = await service.updateProperties()
        await kafkaAck

        expect(person).toBe(createdPerson)
        expect(store.createPerson).toHaveBeenCalled()
        expect(mockEmitIngestionWarning).not.toHaveBeenCalledWith(
            expect.anything(),
            teamId,
            expect.objectContaining({ type: 'distinct_id_case_collision' })
        )
    })

    it('does not warn when the fresh mixed-case distinct id has no lowercased twin', async () => {
        const store = storeCreatingNewPerson()
        const service = buildService('Intaldarryl@gmail.com', store)

        const [, kafkaAck] = await service.updateProperties()
        await kafkaAck

        expect(store.fetchForChecking).toHaveBeenCalledWith(teamId, 'intaldarryl@gmail.com')
        expect(mockEmitIngestionWarning).not.toHaveBeenCalled()
    })

    it('skips the twin lookup entirely for an all-lowercase distinct id', async () => {
        const store = storeCreatingNewPerson()
        const service = buildService('intaldarryl@gmail.com', store)

        const [, kafkaAck] = await service.updateProperties()
        await kafkaAck

        expect(store.fetchForChecking).not.toHaveBeenCalled()
        expect(mockEmitIngestionWarning).not.toHaveBeenCalled()
    })

    it('does not check for a twin when the exact person already exists', async () => {
        const existing = { uuid: new UUIDT().toString(), properties: {} }
        const store = storeCreatingNewPerson({
            fetchForUpdate: jest.fn().mockResolvedValue(existing),
            applyEventOps: jest.fn().mockResolvedValue([existing, []]),
        })
        const service = buildService('Intaldarryl@gmail.com', store)

        const [, kafkaAck] = await service.updateProperties()
        await kafkaAck

        expect(store.fetchForChecking).not.toHaveBeenCalled()
        expect(mockEmitIngestionWarning).not.toHaveBeenCalled()
    })
})
