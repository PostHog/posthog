import { create } from '@bufbuild/protobuf'
import { Code, ConnectError, createRouterTransport } from '@connectrpc/connect'

import { PersonHogService } from '~/common/generated/personhog/personhog/service/v1/service_pb'
import { PersonSchema } from '~/common/generated/personhog/personhog/types/v1/person_pb'
import { TeamId } from '~/types'

import { PersonHogClient } from './client'
import { PersonHogPersonReadRepository } from './personhog-person-read-repository'

jest.mock('~/common/utils/logger')

const textEncoder = new TextEncoder()

function jsonBytes(obj: unknown): Uint8Array {
    return textEncoder.encode(JSON.stringify(obj))
}

const TEAM_ID = 1 as TeamId

function makeProtoPerson(id: bigint = 42n, uuid: string = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee') {
    return create(PersonSchema, {
        id,
        uuid,
        teamId: BigInt(TEAM_ID),
        properties: jsonBytes({ name: 'Test User' }),
        propertiesLastUpdatedAt: jsonBytes({}),
        propertiesLastOperation: jsonBytes({}),
        createdAt: 1704067200000n,
        version: 1n,
        isIdentified: true,
    })
}

type ServiceHandlers = {
    getPersonsByDistinctIds: jest.Mock
    getPersonsByUuids: jest.Mock
    getDistinctIdsForPersons: jest.Mock
}

function createMockClientAndHandlers(): { client: PersonHogClient; handlers: ServiceHandlers } {
    const handlers: ServiceHandlers = {
        getPersonsByDistinctIds: jest.fn().mockResolvedValue({ results: [] }),
        getPersonsByUuids: jest.fn().mockResolvedValue({ persons: [], missingIds: [] }),
        getDistinctIdsForPersons: jest.fn().mockResolvedValue({ personDistinctIds: [] }),
    }

    const transport = createRouterTransport(({ service }) => {
        service(PersonHogService, {
            getPersonsByDistinctIds: handlers.getPersonsByDistinctIds,
            getPersonsByUuids: handlers.getPersonsByUuids,
            getDistinctIdsForPersons: handlers.getDistinctIdsForPersons,
        })
    })

    const client = PersonHogClient.fromTransport(transport)
    return { client, handlers }
}

describe('PersonHogPersonReadRepository', () => {
    describe('fetchPerson', () => {
        it('returns person when found', async () => {
            const { client, handlers } = createMockClientAndHandlers()
            handlers.getPersonsByDistinctIds.mockImplementation(() => ({
                results: [{ person: makeProtoPerson(), key: { teamId: BigInt(TEAM_ID), distinctId: 'user-1' } }],
            }))

            const repo = new PersonHogPersonReadRepository(client)
            const result = await repo.fetchPerson(TEAM_ID, 'user-1')

            expect(result).toBeDefined()
            expect(result!.uuid).toBe('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
            expect(result!.properties).toEqual({ name: 'Test User' })
        })

        it('returns undefined when not found', async () => {
            const { client } = createMockClientAndHandlers()
            const repo = new PersonHogPersonReadRepository(client)
            const result = await repo.fetchPerson(TEAM_ID, 'nonexistent')

            expect(result).toBeUndefined()
        })
    })

    describe('fetchPersonsByDistinctIds', () => {
        it('returns persons with distinct ids', async () => {
            const { client, handlers } = createMockClientAndHandlers()
            handlers.getPersonsByDistinctIds.mockImplementation(() => ({
                results: [{ person: makeProtoPerson(), key: { teamId: BigInt(TEAM_ID), distinctId: 'user-1' } }],
            }))

            const repo = new PersonHogPersonReadRepository(client)
            const result = await repo.fetchPersonsByDistinctIds([{ teamId: TEAM_ID, distinctId: 'user-1' }])

            expect(result).toHaveLength(1)
            expect(result[0].distinct_id).toBe('user-1')
        })

        it('returns empty array for empty input', async () => {
            const { client, handlers } = createMockClientAndHandlers()
            const repo = new PersonHogPersonReadRepository(client)
            const result = await repo.fetchPersonsByDistinctIds([])

            expect(result).toEqual([])
            expect(handlers.getPersonsByDistinctIds).not.toHaveBeenCalled()
        })
    })

    describe('fetchPersonsByPersonIds', () => {
        it('returns persons by uuid', async () => {
            const { client, handlers } = createMockClientAndHandlers()
            handlers.getPersonsByUuids.mockImplementation(() => ({
                persons: [makeProtoPerson()],
                missingIds: [],
            }))

            const repo = new PersonHogPersonReadRepository(client)
            const result = await repo.fetchPersonsByPersonIds([
                { teamId: TEAM_ID, personId: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee' },
            ])

            expect(result).toHaveLength(1)
            expect(result[0].uuid).toBe('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
        })

        it('returns empty array for empty input', async () => {
            const { client, handlers } = createMockClientAndHandlers()
            const repo = new PersonHogPersonReadRepository(client)
            const result = await repo.fetchPersonsByPersonIds([])

            expect(result).toEqual([])
            expect(handlers.getPersonsByUuids).not.toHaveBeenCalled()
        })
    })

    describe('fetchDistinctIdsForPersons', () => {
        it('returns distinct ids keyed by person id', async () => {
            const { client, handlers } = createMockClientAndHandlers()
            handlers.getDistinctIdsForPersons.mockImplementation(() => ({
                personDistinctIds: [
                    { personId: 42n, distinctIds: [{ distinctId: 'user-1' }, { distinctId: 'user-2' }] },
                ],
            }))

            const repo = new PersonHogPersonReadRepository(client)
            const result = await repo.fetchDistinctIdsForPersons(TEAM_ID, ['42'])

            expect(result).toEqual({ '42': ['user-1', 'user-2'] })
        })

        it('returns empty record for empty input', async () => {
            const { client, handlers } = createMockClientAndHandlers()
            const repo = new PersonHogPersonReadRepository(client)
            const result = await repo.fetchDistinctIdsForPersons(TEAM_ID, [])

            expect(result).toEqual({})
            expect(handlers.getDistinctIdsForPersons).not.toHaveBeenCalled()
        })
    })

    describe('retry behavior', () => {
        it.each([
            ['Unavailable', Code.Unavailable],
            ['DeadlineExceeded', Code.DeadlineExceeded],
            ['ResourceExhausted', Code.ResourceExhausted],
            ['Aborted', Code.Aborted],
            ['Internal', Code.Internal],
            ['Unknown', Code.Unknown],
        ])('retries on %s and succeeds', async (_name, code) => {
            const { client, handlers } = createMockClientAndHandlers()
            let callCount = 0
            handlers.getPersonsByDistinctIds.mockImplementation(() => {
                callCount++
                if (callCount === 1) {
                    throw new ConnectError('transient', code)
                }
                return {
                    results: [{ person: makeProtoPerson(), key: { teamId: BigInt(TEAM_ID), distinctId: 'user-1' } }],
                }
            })

            const repo = new PersonHogPersonReadRepository(client)
            const result = await repo.fetchPerson(TEAM_ID, 'user-1')

            expect(result).toBeDefined()
            expect(callCount).toBe(2)
        })

        it.each([
            ['InvalidArgument', Code.InvalidArgument],
            ['NotFound', Code.NotFound],
            ['AlreadyExists', Code.AlreadyExists],
            ['PermissionDenied', Code.PermissionDenied],
            ['Unauthenticated', Code.Unauthenticated],
            ['Unimplemented', Code.Unimplemented],
            ['FailedPrecondition', Code.FailedPrecondition],
            ['OutOfRange', Code.OutOfRange],
            ['DataLoss', Code.DataLoss],
            ['Canceled', Code.Canceled],
        ])('does not retry on %s', async (_name, code) => {
            const { client, handlers } = createMockClientAndHandlers()
            handlers.getPersonsByDistinctIds.mockImplementation(() => {
                throw new ConnectError('non-retryable', code)
            })

            const repo = new PersonHogPersonReadRepository(client)
            await expect(repo.fetchPerson(TEAM_ID, 'user-1')).rejects.toThrow(ConnectError)

            expect(handlers.getPersonsByDistinctIds).toHaveBeenCalledTimes(1)
        })

        it('throws after max retries exhausted', async () => {
            const { client, handlers } = createMockClientAndHandlers()
            handlers.getPersonsByDistinctIds.mockImplementation(() => {
                throw new ConnectError('unavailable', Code.Unavailable)
            })

            const repo = new PersonHogPersonReadRepository(client)
            await expect(repo.fetchPerson(TEAM_ID, 'user-1')).rejects.toThrow(ConnectError)

            // 1 initial + 2 retries = 3 total
            expect(handlers.getPersonsByDistinctIds).toHaveBeenCalledTimes(3)
        })
    })
})
