import { create } from '@bufbuild/protobuf'
import { type ServiceImpl, createClient, createRouterTransport } from '@connectrpc/connect'

import { PersonHogService } from '~/common/generated/personhog/personhog/service/v1/service_pb'
import { PersonSchema } from '~/common/generated/personhog/personhog/types/v1/person_pb'
import type {
    GetPersonsByDistinctIdsRequest,
    GetPersonsByUuidsRequest,
} from '~/common/generated/personhog/personhog/types/v1/person_pb'

import { PersonHogPersonOperations } from './persons'

const textEncoder = new TextEncoder()

function jsonBytes(obj: unknown): Uint8Array {
    return textEncoder.encode(JSON.stringify(obj))
}

function makeProtoPerson(id: number, uuid: string, teamId: number) {
    return create(PersonSchema, {
        id: BigInt(id),
        uuid,
        teamId: BigInt(teamId),
        properties: jsonBytes({ name: `person-${id}` }),
        propertiesLastUpdatedAt: jsonBytes({}),
        propertiesLastOperation: jsonBytes({}),
        createdAt: BigInt(Date.now()),
        version: 1n,
        isIdentified: true,
    })
}

const SERVICE_DEFAULTS: ServiceImpl<typeof PersonHogService> = {
    getGroup: () => ({}),
    getGroups: () => ({ groups: [], missingGroups: [] }),
    getGroupsBatch: () => ({ results: [] }),
    listGroups: () => ({ groups: [], hasMore: false }),
    getGroupTypeMappingsByTeamId: () => ({ mappings: [] }),
    getGroupTypeMappingsByTeamIds: () => ({ results: [] }),
    getGroupTypeMappingsByProjectId: () => ({ mappings: [] }),
    getGroupTypeMappingsByProjectIds: () => ({ results: [] }),
    getGroupTypeMappingByDashboardId: () => ({}),
    countGroupTypeMappings: () => ({ counts: [] }),
    createGroup: () => ({}),
    updateGroup: () => ({ updated: false }),
    deleteGroupsBatchForTeam: () => ({ deletedCount: 0n }),
    updateGroupTypeMapping: () => ({}),
    deleteGroupTypeMapping: () => ({ deleted: false }),
    deleteGroupTypeMappingsBatchForTeam: () => ({ deletedCount: 0n }),
    getPerson: () => ({}),
    getPersons: () => ({ persons: [] }),
    getPersonByUuid: () => ({}),
    getPersonsByUuids: () => ({ persons: [] }),
    getPersonByDistinctId: () => ({}),
    getPersonsByDistinctIdsInTeam: () => ({ results: [] }),
    getPersonsByDistinctIds: () => ({ results: [] }),
    getDistinctIdsForPerson: () => ({ distinctIds: [] }),
    getDistinctIdsForPersons: () => ({ personDistinctIds: [] }),
    getHashKeyOverrideContext: () => ({ results: [] }),
    upsertHashKeyOverrides: () => ({}),
    deleteHashKeyOverridesByTeams: () => ({}),
    checkCohortMembership: () => ({ memberships: [] }),
    countCohortMembers: () => ({ count: 0n }),
    deleteCohortMember: () => ({ deleted: false }),
    deleteCohortMembersBulk: () => ({ deletedCount: 0n }),
    insertCohortMembers: () => ({ insertedCount: 0n }),
    listCohortMemberIds: () => ({ personIds: [], nextCursor: 0n }),
    updatePersonProperties: () => ({}),
    deletePersons: () => ({ deletedCount: 0n }),
    deletePersonsBatchForTeam: () => ({ deletedCount: 0n }),
    splitPerson: () => ({ splits: [] }),
}

function createOperations(overrides: Partial<ServiceImpl<typeof PersonHogService>> = {}): {
    ops: PersonHogPersonOperations
    handlers: { getPersonsByDistinctIds: jest.Mock; getPersonsByUuids: jest.Mock }
} {
    const handlers = {
        getPersonsByDistinctIds: jest.fn(() => ({ results: [] })),
        getPersonsByUuids: jest.fn(() => ({ persons: [] })),
    }

    const transport = createRouterTransport(({ service }) => {
        service(PersonHogService, {
            ...SERVICE_DEFAULTS,
            ...handlers,
            ...overrides,
        })
    })

    const client = createClient(PersonHogService, transport)
    const ops = new PersonHogPersonOperations(client)
    return { ops, handlers }
}

describe('PersonHogPersonOperations', () => {
    describe.each([
        {
            method: 'fetchPersonsByDistinctIds' as const,
            handler: 'getPersonsByDistinctIds' as const,
            makeItem: (i: number) => ({ teamId: 1, distinctId: `d-${i}` }),
        },
        {
            method: 'fetchPersonsByPersonIds' as const,
            handler: 'getPersonsByUuids' as const,
            makeItem: (i: number) => ({ teamId: 1, personId: `uuid-${i}` }),
        },
    ])('$method batching', ({ method, handler, makeItem }) => {
        const invoke = (ops: PersonHogPersonOperations, count: number): Promise<any> =>
            (ops[method] as any)(Array.from({ length: count }, (_, i) => makeItem(i)))

        it('sends a single RPC when under the batch limit', async () => {
            const { ops, handlers } = createOperations()
            await invoke(ops, 10)
            expect(handlers[handler]).toHaveBeenCalledTimes(1)
        })

        it('splits into multiple RPCs when over the batch limit', async () => {
            const { ops, handlers } = createOperations()
            await invoke(ops, 400)
            expect(handlers[handler]).toHaveBeenCalledTimes(2)
        })

        it('handles exact batch boundary without duplicating or dropping', async () => {
            const { ops, handlers } = createOperations()
            await invoke(ops, 250)
            expect(handlers[handler]).toHaveBeenCalledTimes(1)
        })
    })

    describe('fetchPersonsByDistinctIds', () => {
        it('merges results from multiple batches', async () => {
            const handler = jest.fn()
            let callCount = 0
            handler.mockImplementation((req: GetPersonsByDistinctIdsRequest) => {
                callCount++
                return {
                    results: req.teamDistinctIds.map((td) => ({
                        key: { teamId: td.teamId, distinctId: td.distinctId },
                        person: makeProtoPerson(
                            callCount * 1000 + Number(td.teamId),
                            `uuid-${td.distinctId}`,
                            Number(td.teamId)
                        ),
                    })),
                }
            })

            const { ops } = createOperations({ getPersonsByDistinctIds: handler })
            const items = Array.from({ length: 300 }, (_, i) => ({ teamId: 1, distinctId: `d-${i}` }))

            const results = await ops.fetchPersonsByDistinctIds(items)

            expect(handler).toHaveBeenCalledTimes(2)
            expect(results).toHaveLength(300)
        })
    })

    describe('fetchPersonsByPersonIds', () => {
        it('merges results from multiple batches across teams', async () => {
            const handler = jest.fn()
            handler.mockImplementation((req: GetPersonsByUuidsRequest) => ({
                persons: req.uuids.map((uuid, i) => makeProtoPerson(i, uuid, Number(req.teamId))),
            }))

            const { ops } = createOperations({ getPersonsByUuids: handler })
            const items = [
                ...Array.from({ length: 300 }, (_, i) => ({ teamId: 1, personId: `uuid-t1-${i}` })),
                ...Array.from({ length: 100 }, (_, i) => ({ teamId: 2, personId: `uuid-t2-${i}` })),
            ]

            const results = await ops.fetchPersonsByPersonIds(items)

            // team 1: 2 batches (250 + 50), team 2: 1 batch (100)
            expect(handler).toHaveBeenCalledTimes(3)
            expect(results).toHaveLength(400)
        })
    })
})
