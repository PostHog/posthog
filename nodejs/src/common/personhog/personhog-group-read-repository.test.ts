import { Code, ConnectError, createRouterTransport } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { PersonHogService } from '~/common/generated/personhog/personhog/service/v1/service_pb'
import { TeamId } from '~/types'

import { PersonHogClient } from './client'
import { PersonHogGroupReadRepository } from './personhog-group-read-repository'

jest.mock('~/common/utils/logger')

const TEAM_ID = 1 as TeamId

type ServiceHandlers = {
    getGroupsBatch: jest.Mock
    getGroupTypeMappingsByTeamIds: jest.Mock
}

function createMockClientAndHandlers(): { client: PersonHogClient; handlers: ServiceHandlers } {
    const handlers: ServiceHandlers = {
        getGroupsBatch: jest.fn().mockReturnValue({ results: [] }),
        getGroupTypeMappingsByTeamIds: jest.fn().mockReturnValue({ results: [] }),
    }

    const transport = createRouterTransport(({ service }) => {
        service(PersonHogService, {
            getGroupsBatch: handlers.getGroupsBatch,
            getGroupTypeMappingsByTeamIds: handlers.getGroupTypeMappingsByTeamIds,
        })
    })

    const client = PersonHogClient.fromTransport(transport)
    return { client, handlers }
}

const textEncoder = new TextEncoder()

function jsonBytes(obj: unknown): Uint8Array {
    return textEncoder.encode(JSON.stringify(obj))
}

describe('PersonHogGroupReadRepository', () => {
    describe('fetchGroupsByKeys', () => {
        it('returns group properties for matching keys', async () => {
            const { client, handlers } = createMockClientAndHandlers()
            handlers.getGroupsBatch.mockReturnValue({
                results: [
                    {
                        key: { teamId: BigInt(TEAM_ID), groupTypeIndex: 0, groupKey: 'company-1' },
                        group: {
                            id: 1n,
                            teamId: BigInt(TEAM_ID),
                            groupTypeIndex: 0,
                            groupKey: 'company-1',
                            groupProperties: jsonBytes({ name: 'Acme Inc' }),
                            propertiesLastUpdatedAt: jsonBytes({}),
                            propertiesLastOperation: jsonBytes({}),
                            createdAt: 1704067200000n,
                            version: 1n,
                        },
                    },
                ],
            })

            const repo = new PersonHogGroupReadRepository(client)
            const result = await repo.fetchGroupsByKeys([TEAM_ID], [0], ['company-1'])

            expect(result).toHaveLength(1)
            expect(result[0]).toEqual({
                team_id: TEAM_ID,
                group_type_index: 0,
                group_key: 'company-1',
                group_properties: { name: 'Acme Inc' },
                created_at: DateTime.fromMillis(1704067200000, { zone: 'utc' }),
                version: 1,
            })
        })

        it('returns empty array for empty input', async () => {
            const { client, handlers } = createMockClientAndHandlers()
            const repo = new PersonHogGroupReadRepository(client)
            const result = await repo.fetchGroupsByKeys([], [], [])

            expect(result).toEqual([])
            expect(handlers.getGroupsBatch).not.toHaveBeenCalled()
        })
    })

    describe('fetchGroupTypesByTeamIds', () => {
        it('returns group type mappings keyed by team id', async () => {
            const { client, handlers } = createMockClientAndHandlers()
            handlers.getGroupTypeMappingsByTeamIds.mockReturnValue({
                results: [
                    {
                        key: BigInt(TEAM_ID),
                        mappings: [
                            { groupType: 'company', groupTypeIndex: 0 },
                            { groupType: 'project', groupTypeIndex: 1 },
                        ],
                    },
                ],
            })

            const repo = new PersonHogGroupReadRepository(client)
            const result = await repo.fetchGroupTypesByTeamIds([TEAM_ID])

            expect(result).toEqual({
                [String(TEAM_ID)]: [
                    { group_type: 'company', group_type_index: 0 },
                    { group_type: 'project', group_type_index: 1 },
                ],
            })
        })

        it('returns empty record for empty input', async () => {
            const { client, handlers } = createMockClientAndHandlers()
            const repo = new PersonHogGroupReadRepository(client)
            const result = await repo.fetchGroupTypesByTeamIds([])

            expect(result).toEqual({})
            expect(handlers.getGroupTypeMappingsByTeamIds).not.toHaveBeenCalled()
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
            handlers.getGroupsBatch.mockImplementation(() => {
                callCount++
                if (callCount === 1) {
                    throw new ConnectError('transient', code)
                }
                return { results: [] }
            })

            const repo = new PersonHogGroupReadRepository(client)
            const result = await repo.fetchGroupsByKeys([TEAM_ID], [0], ['key'])

            expect(result).toEqual([])
            expect(callCount).toBe(2)
        })

        it.each([
            ['InvalidArgument', Code.InvalidArgument],
            ['NotFound', Code.NotFound],
            ['PermissionDenied', Code.PermissionDenied],
            ['Unauthenticated', Code.Unauthenticated],
            ['Unimplemented', Code.Unimplemented],
        ])('does not retry on %s', async (_name, code) => {
            const { client, handlers } = createMockClientAndHandlers()
            handlers.getGroupsBatch.mockImplementation(() => {
                throw new ConnectError('non-retryable', code)
            })

            const repo = new PersonHogGroupReadRepository(client)
            await expect(repo.fetchGroupsByKeys([TEAM_ID], [0], ['key'])).rejects.toThrow(ConnectError)

            expect(handlers.getGroupsBatch).toHaveBeenCalledTimes(1)
        })

        it('throws after max retries exhausted', async () => {
            const { client, handlers } = createMockClientAndHandlers()
            handlers.getGroupsBatch.mockImplementation(() => {
                throw new ConnectError('unavailable', Code.Unavailable)
            })

            const repo = new PersonHogGroupReadRepository(client)
            await expect(repo.fetchGroupsByKeys([TEAM_ID], [0], ['key'])).rejects.toThrow(ConnectError)

            // 1 initial + 2 retries = 3 total
            expect(handlers.getGroupsBatch).toHaveBeenCalledTimes(3)
        })
    })
})
