import { create } from '@bufbuild/protobuf'
import { Code, ConnectError, createRouterTransport } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { PersonHogService } from '~/common/generated/personhog/personhog/service/v1/service_pb'
import { TeamDistinctIdSchema } from '~/common/generated/personhog/personhog/types/v1/common_pb'
import {
    GetDistinctIdsForPersonsResponseSchema,
    PersonDistinctIdsSchema,
    PersonSchema,
    PersonWithTeamDistinctIdSchema,
    PersonsByDistinctIdsResponseSchema,
    PersonsResponseSchema,
} from '~/common/generated/personhog/personhog/types/v1/person_pb'
import { PersonHogClient } from '~/common/personhog/client'
import { PersonHogPersonReadRepository } from '~/common/personhog/personhog-person-read-repository'

import { PersonsManagerService } from './persons-manager.service'

jest.mock('~/common/utils/logger')

const textEncoder = new TextEncoder()

function jsonBytes(obj: unknown): Uint8Array {
    return textEncoder.encode(JSON.stringify(obj))
}

type TestPerson = {
    id: string
    uuid: string
    teamId: number
    properties: Record<string, any>
    distinctIds: string[]
}

function makeProtoPerson(p: TestPerson) {
    return create(PersonSchema, {
        id: BigInt(p.id),
        uuid: p.uuid,
        teamId: BigInt(p.teamId),
        properties: jsonBytes(p.properties),
        propertiesLastUpdatedAt: jsonBytes({}),
        propertiesLastOperation: jsonBytes({}),
        createdAt: BigInt(DateTime.fromISO('2024-01-01T00:00:00Z', { zone: 'utc' }).toMillis()),
        version: 1n,
        isIdentified: true,
    })
}

function createTestPersonHogPersonReadRepository(persons: TestPerson[]): PersonHogPersonReadRepository {
    const transport = createRouterTransport(({ service }) => {
        service(PersonHogService, {
            getPersonsByDistinctIds: (req) => {
                const results = []
                for (const td of req.teamDistinctIds) {
                    const teamId = Number(td.teamId)
                    const match = persons.find((p) => p.teamId === teamId && p.distinctIds.includes(td.distinctId))
                    if (match) {
                        results.push(
                            create(PersonWithTeamDistinctIdSchema, {
                                person: makeProtoPerson(match),
                                key: create(TeamDistinctIdSchema, {
                                    teamId: td.teamId,
                                    distinctId: td.distinctId,
                                }),
                            })
                        )
                    }
                }
                return create(PersonsByDistinctIdsResponseSchema, { results })
            },
            getPersonsByUuids: (req) => {
                const teamId = Number(req.teamId)
                const matched = persons.filter((p) => p.teamId === teamId && req.uuids.includes(p.uuid))
                return create(PersonsResponseSchema, {
                    persons: matched.map(makeProtoPerson),
                    missingIds: [],
                })
            },
            getDistinctIdsForPersons: (req) => {
                const teamId = Number(req.teamId)
                const personDistinctIds = []
                for (const personId of req.personIds) {
                    const match = persons.find((p) => p.teamId === teamId && p.id === String(personId))
                    if (match && match.distinctIds.length > 0) {
                        const limit = req.limitPerPerson ? Number(req.limitPerPerson) : undefined
                        const ids = limit ? match.distinctIds.slice(0, limit) : match.distinctIds
                        personDistinctIds.push(
                            create(PersonDistinctIdsSchema, {
                                personId,
                                distinctIds: ids.map((d) => ({ distinctId: d })),
                            })
                        )
                    }
                }
                return create(GetDistinctIdsForPersonsResponseSchema, { personDistinctIds })
            },
        })
    })

    const client = PersonHogClient.fromTransport(transport)
    return new PersonHogPersonReadRepository(client, 'test')
}

const TEAM_1 = 1
const TEAM_2 = 2

const TEST_PERSONS: TestPerson[] = [
    {
        id: '1',
        uuid: 'aaaaaaaa-0000-0000-0000-000000000001',
        teamId: TEAM_1,
        properties: { foo: '1' },
        distinctIds: ['distinct_id_A_1', 'distinct_id_A_2', 'distinct_id_A_3'],
    },
    {
        id: '2',
        uuid: 'aaaaaaaa-0000-0000-0000-000000000002',
        teamId: TEAM_1,
        properties: { foo: '2' },
        distinctIds: ['distinct_id_B_1'],
    },
    {
        id: '3',
        uuid: 'aaaaaaaa-0000-0000-0000-000000000003',
        teamId: TEAM_2,
        properties: { foo: '3' },
        distinctIds: ['distinct_id_A_1'],
    },
]

describe('PersonsManagerService', () => {
    jest.setTimeout(1000)

    const mockTeamManager = {
        getTeam: jest.fn().mockImplementation((teamId: number) => {
            if (teamId === TEAM_1 || teamId === TEAM_2) {
                return Promise.resolve({
                    id: teamId,
                    uuid: `team-uuid-${teamId}`,
                    organization_id: 'org-1',
                    person_display_name_properties: [],
                })
            }
            return Promise.resolve(null)
        }),
        hasAvailableFeature: jest.fn().mockResolvedValue(true),
    } as any

    let repo: PersonHogPersonReadRepository
    let manager: PersonsManagerService

    beforeEach(() => {
        jest.restoreAllMocks()
        repo = createTestPersonHogPersonReadRepository(TEST_PERSONS)
        manager = new PersonsManagerService(mockTeamManager, repo, 'http://localhost:8000')
    })

    describe('getCyclotronPerson with distinct_id', () => {
        it('returns the persons requested', async () => {
            const res = await Promise.all([
                manager.getCyclotronPerson(TEAM_1, 'distinct_id_A_1', 'distinct_id'),
                manager.getCyclotronPerson(TEAM_1, 'distinct_id_B_1', 'distinct_id'),
            ])

            expect(res).toEqual([
                {
                    id: TEST_PERSONS[0].uuid,
                    properties: { foo: '1' },
                    name: 'distinct_id_A_1',
                    url: `http://localhost:8000/project/${TEAM_1}/person/distinct_id_A_1`,
                    distinct_id: 'distinct_id_A_1',
                },
                {
                    id: TEST_PERSONS[1].uuid,
                    properties: { foo: '2' },
                    name: 'distinct_id_B_1',
                    url: `http://localhost:8000/project/${TEAM_1}/person/distinct_id_B_1`,
                    distinct_id: 'distinct_id_B_1',
                },
            ])
        })

        it('handles distinct IDs containing colons', async () => {
            const personsWithColons: TestPerson[] = [
                ...TEST_PERSONS,
                {
                    id: '10',
                    uuid: 'bbbbbbbb-0000-0000-0000-000000000010',
                    teamId: TEAM_1,
                    properties: { foo: 'colon1' },
                    distinctIds: ['foo:distinct_id_A_1'],
                },
                {
                    id: '11',
                    uuid: 'bbbbbbbb-0000-0000-0000-000000000011',
                    teamId: TEAM_1,
                    properties: { foo: 'colon2' },
                    distinctIds: ['foo:bar:distinct_id_B_1'],
                },
            ]
            const colonRepo = createTestPersonHogPersonReadRepository(personsWithColons)
            const colonManager = new PersonsManagerService(mockTeamManager, colonRepo, 'http://localhost:8000')

            const res = await Promise.all([
                colonManager.getCyclotronPerson(TEAM_1, 'foo:distinct_id_A_1', 'distinct_id'),
                colonManager.getCyclotronPerson(TEAM_1, 'foo:bar:distinct_id_B_1', 'distinct_id'),
            ])

            expect(res[0]!.distinct_id).toBe('foo:distinct_id_A_1')
            expect(res[0]!.url).toBe(`http://localhost:8000/project/${TEAM_1}/person/foo%3Adistinct_id_A_1`)
            expect(res[1]!.distinct_id).toBe('foo:bar:distinct_id_B_1')
            expect(res[1]!.url).toBe(`http://localhost:8000/project/${TEAM_1}/person/foo%3Abar%3Adistinct_id_B_1`)
        })

        it('returns different persons for different teams', async () => {
            const res = await Promise.all([
                manager.getCyclotronPerson(TEAM_1, 'distinct_id_A_1', 'distinct_id'),
                manager.getCyclotronPerson(TEAM_2, 'distinct_id_A_1', 'distinct_id'),
            ])

            expect(res[0]!.properties).toEqual({ foo: '1' })
            expect(res[1]!.properties).toEqual({ foo: '3' })
        })

        it('returns the same person for different distinct ids', async () => {
            const res = await Promise.all([
                manager.getCyclotronPerson(TEAM_1, 'distinct_id_A_1', 'distinct_id'),
                manager.getCyclotronPerson(TEAM_1, 'distinct_id_A_2', 'distinct_id'),
            ])

            expect(res[0]!.id).toEqual(res[1]!.id)
            expect(res[0]!.properties).toEqual(res[1]!.properties)
        })

        it('returns null when person does not exist', async () => {
            const result = await manager.getCyclotronPerson(TEAM_1, 'nonexistent', 'distinct_id')
            expect(result).toBeNull()
        })

        it('returns null when team does not exist', async () => {
            const result = await manager.getCyclotronPerson(99999, 'distinct_id_A_1', 'distinct_id')
            expect(result).toBeNull()
        })

        it('encodes special characters in distinct_id for URL', async () => {
            const personsWithEmail: TestPerson[] = [
                ...TEST_PERSONS,
                {
                    id: '20',
                    uuid: 'cccccccc-0000-0000-0000-000000000020',
                    teamId: TEAM_1,
                    properties: {},
                    distinctIds: ['user@example.com'],
                },
            ]
            const emailRepo = createTestPersonHogPersonReadRepository(personsWithEmail)
            const emailManager = new PersonsManagerService(mockTeamManager, emailRepo, 'http://localhost:8000')

            const result = await emailManager.getCyclotronPerson(TEAM_1, 'user@example.com', 'distinct_id')

            expect(result).toBeDefined()
            expect(result!.url).toBe(`http://localhost:8000/project/${TEAM_1}/person/user%40example.com`)
        })
    })

    describe('getCyclotronPerson with person_id', () => {
        it('returns a person by UUID and resolves distinct_id', async () => {
            const result = await manager.getCyclotronPerson(TEAM_1, TEST_PERSONS[0].uuid, 'person_id')

            expect(result).toEqual(
                expect.objectContaining({
                    id: TEST_PERSONS[0].uuid,
                    properties: { foo: '1' },
                    distinct_id: 'distinct_id_A_1',
                })
            )
        })

        it('returns null for a UUID that does not exist', async () => {
            const result = await manager.getCyclotronPerson(TEAM_1, 'zzzzzzzz-0000-0000-0000-000000000000', 'person_id')
            expect(result).toBeNull()
        })

        it('returns the correct person for each team when UUIDs differ', async () => {
            const res = await Promise.all([
                manager.getCyclotronPerson(TEAM_1, TEST_PERSONS[0].uuid, 'person_id'),
                manager.getCyclotronPerson(TEAM_2, TEST_PERSONS[2].uuid, 'person_id'),
            ])

            expect(res).toEqual([
                expect.objectContaining({ id: TEST_PERSONS[0].uuid, properties: { foo: '1' } }),
                expect.objectContaining({ id: TEST_PERSONS[2].uuid, properties: { foo: '3' } }),
            ])
        })

        it('returns null when queried under the wrong team', async () => {
            const result = await manager.getCyclotronPerson(TEAM_2, TEST_PERSONS[0].uuid, 'person_id')
            expect(result).toBeNull()
        })
    })

    describe('error handling', () => {
        it('propagates errors when personhog is unavailable', async () => {
            const failingTransport = createRouterTransport(({ service }) => {
                service(PersonHogService, {
                    getPersonsByDistinctIds: () => {
                        throw new ConnectError('unavailable', Code.Unavailable)
                    },
                })
            })
            const failingClient = PersonHogClient.fromTransport(failingTransport)
            const failingRepo = new PersonHogPersonReadRepository(failingClient, 'test')
            const failingManager = new PersonsManagerService(mockTeamManager, failingRepo, 'http://localhost:8000')

            await expect(failingManager.getCyclotronPerson(TEAM_1, 'distinct_id_A_1', 'distinct_id')).rejects.toThrow()
        })
    })
})
