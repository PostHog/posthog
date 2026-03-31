import { DateTime } from 'luxon'

import { HogFlow } from '~/schema/hogflow'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { createTeam, getFirstTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { PostgresPersonRepository } from '~/worker/ingestion/persons/repositories/postgres-person-repository'

import { PersonHogClient } from '../../ingestion/personhog/client'
import { PersonHogPersonRepository } from '../../ingestion/personhog/personhog-person-repository'
import { Hub, InternalPerson, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { UUIDT } from '../../utils/utils'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { createHogFlowInvocationContext, insertHogFlow } from '../_tests/fixtures-hogflows'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationResult,
    HogFlowInvocationContext,
} from '../types'
import { CdpCyclotronWorkerHogFlow } from './cdp-cyclotron-worker-hogflow.consumer'

jest.setTimeout(1000)

type MockPersonHogClient = {
    groups: jest.Mocked<
        Pick<
            PersonHogClient['groups'],
            'fetchGroup' | 'fetchGroupsByKeys' | 'fetchGroupTypesByTeamIds' | 'fetchGroupTypesByProjectIds'
        >
    >
    persons: jest.Mocked<Pick<PersonHogClient['persons'], 'fetchPersonsByDistinctIds' | 'fetchPersonsByPersonIds'>>
}

describe('CdpCyclotronWorkerHogFlow with PersonHog', () => {
    let hub: Hub
    let postgresPersonRepo: PostgresPersonRepository
    let team: Team
    let team2: Team
    let hogFlows: HogFlow[]

    const createSerializedHogFlowInvocation = (
        hogFlow: HogFlow,
        _context: Partial<HogFlowInvocationContext> = {}
    ): CyclotronJobInvocation => {
        const context = createHogFlowInvocationContext(_context)
        return {
            id: new UUIDT().toString(),
            state: { ...context },
            teamId: hogFlow.team_id,
            functionId: hogFlow.id,
            queue: 'hogflow',
            queuePriority: 0,
        }
    }

    const createPerson = async (
        teamId: number,
        uuid: string,
        distinctId: string,
        properties: any
    ): Promise<InternalPerson> => {
        const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()
        const result = await postgresPersonRepo.createPerson(TIMESTAMP, properties, {}, {}, teamId, null, true, uuid, {
            distinctId,
        })
        if (!result.success) {
            throw new Error('Failed to create person')
        }
        return result.person
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        postgresPersonRepo = new PostgresPersonRepository(hub.postgres)
        team = await getFirstTeam(hub.postgres)
        const team2Id = await createTeam(hub.postgres, team.organization_id)
        team2 = (await getTeam(hub.postgres, team2Id))!

        hogFlows = []
        hogFlows.push(
            await insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withName('Test Hog Flow team 1')
                    .withTeamId(team.id)
                    .withStatus('active')
                    .withSimpleWorkflow()
                    .build()
            )
        )
        hogFlows.push(
            await insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withName('Test Hog Flow team 2')
                    .withTeamId(team2.id)
                    .withStatus('active')
                    .withSimpleWorkflow()
                    .build()
            )
        )
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await closeHub(hub)
    })

    function createProcessorWithPersonHog(grpcClient: MockPersonHogClient): CdpCyclotronWorkerHogFlow {
        const personhogRepo = new PersonHogPersonRepository(
            postgresPersonRepo,
            grpcClient as unknown as PersonHogClient,
            100,
            'test'
        )
        const deps = {
            ...createCdpConsumerDeps(hub),
            personRepository: personhogRepo,
        }
        return new CdpCyclotronWorkerHogFlow(hub, deps)
    }

    /**
     * Run the same invocations through both postgres-only and personhog paths,
     * returning both result sets for comparison.
     */
    async function runWithBothPaths(invocations: CyclotronJobInvocation[], grpcClient: MockPersonHogClient) {
        // Postgres-only path
        const postgresProcessor = new CdpCyclotronWorkerHogFlow(hub, createCdpConsumerDeps(hub))
        const postgresResults = (await postgresProcessor.processInvocations(
            invocations
        )) as CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]

        // PersonHog path
        const personhogProcessor = createProcessorWithPersonHog(grpcClient)
        // Re-create invocations with fresh IDs since processInvocations may mutate state
        const freshInvocations = invocations.map((inv) => ({ ...inv, id: new UUIDT().toString() }))
        const personhogResults = (await personhogProcessor.processInvocations(
            freshInvocations
        )) as CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]

        return { postgresResults, personhogResults }
    }

    function extractPersonData(results: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]) {
        return results.map((r) => ({
            personName: r.invocation.person?.properties?.name,
            personId: r.invocation.person?.id,
            filterGlobalsPerson: r.invocation.filterGlobals?.person
                ? {
                      id: r.invocation.filterGlobals.person.id,
                      properties: r.invocation.filterGlobals.person.properties,
                  }
                : null,
        }))
    }

    describe('person resolution parity with postgres', () => {
        let mockGrpc: MockPersonHogClient

        beforeEach(async () => {
            await createPerson(team.id, 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1', 'distinct_A_1', {
                name: 'Person A 1',
            })
            await createPerson(team.id, 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e2', 'distinct_A_2', {
                name: 'Person A 2',
            })
            await createPerson(team2.id, 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e3', 'distinct_A_1', {
                name: 'Person A 3',
            })

            // Create a mock gRPC client that delegates to postgres (simulates what
            // a real personhog-router would return)
            mockGrpc = {
                groups: {
                    fetchGroup: jest.fn(),
                    fetchGroupsByKeys: jest.fn(),
                    fetchGroupTypesByTeamIds: jest.fn(),
                    fetchGroupTypesByProjectIds: jest.fn(),
                },
                persons: {
                    fetchPersonsByDistinctIds: jest
                        .fn()
                        .mockImplementation(async (teamPersons: { teamId: number; distinctId: string }[]) =>
                            postgresPersonRepo.fetchPersonsByDistinctIds(teamPersons)
                        ),
                    fetchPersonsByPersonIds: jest
                        .fn()
                        .mockImplementation(async (teamPersons: { teamId: number; personId: string }[]) =>
                            postgresPersonRepo.fetchPersonsByPersonIds(teamPersons)
                        ),
                },
            }
        })

        it('produces identical person data for multi-team distinct_id lookups', async () => {
            const invocations = [
                createSerializedHogFlowInvocation(hogFlows[0], {
                    event: { distinct_id: 'distinct_A_1', properties: { foo: 'bar1' } } as any,
                }),
                createSerializedHogFlowInvocation(hogFlows[0], {
                    event: { distinct_id: 'distinct_A_2', properties: { foo: 'bar2' } } as any,
                }),
                createSerializedHogFlowInvocation(hogFlows[1], {
                    event: { distinct_id: 'distinct_A_1', properties: { foo: 'bar3' } } as any,
                }),
            ]

            const { postgresResults, personhogResults } = await runWithBothPaths(invocations, mockGrpc)

            expect(extractPersonData(personhogResults)).toEqual(extractPersonData(postgresResults))
            expect(mockGrpc.persons.fetchPersonsByDistinctIds).toHaveBeenCalled()
        })

        it('produces identical output for missing persons', async () => {
            const invocations = [
                createSerializedHogFlowInvocation(hogFlows[0], {
                    event: { distinct_id: 'missing_person', properties: { foo: 'bar' } } as any,
                }),
            ]

            const { postgresResults, personhogResults } = await runWithBothPaths(invocations, mockGrpc)

            expect(extractPersonData(personhogResults)).toEqual(extractPersonData(postgresResults))
            expect(personhogResults[0].invocation.person).toBeUndefined()
        })

        it('produces identical output for personId lookups (batch invocations)', async () => {
            const personUuid = 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1'

            const invocations = [
                createSerializedHogFlowInvocation(hogFlows[0], {
                    event: { distinct_id: '', properties: { foo: 'batch' } } as any,
                    personId: personUuid,
                }),
            ]

            const { postgresResults, personhogResults } = await runWithBothPaths(invocations, mockGrpc)

            expect(extractPersonData(personhogResults)).toEqual(extractPersonData(postgresResults))
            expect(personhogResults[0].invocation.person?.properties).toEqual({ name: 'Person A 1' })
        })
    })

    describe('grpc failure falls back to postgres', () => {
        it('falls back gracefully and produces correct results when gRPC fails', async () => {
            await createPerson(team.id, 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1', 'distinct_A_1', {
                name: 'Person A 1',
            })

            const failingGrpc: MockPersonHogClient = {
                groups: {
                    fetchGroup: jest.fn(),
                    fetchGroupsByKeys: jest.fn(),
                    fetchGroupTypesByTeamIds: jest.fn(),
                    fetchGroupTypesByProjectIds: jest.fn(),
                },
                persons: {
                    fetchPersonsByDistinctIds: jest.fn().mockRejectedValue(new Error('gRPC unavailable')),
                    fetchPersonsByPersonIds: jest.fn().mockRejectedValue(new Error('gRPC unavailable')),
                },
            }

            const processor = createProcessorWithPersonHog(failingGrpc)

            const invocations = [
                createSerializedHogFlowInvocation(hogFlows[0], {
                    event: { distinct_id: 'distinct_A_1', properties: { foo: 'bar' } } as any,
                }),
            ]

            const results = (await processor.processInvocations(
                invocations
            )) as CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]

            expect(results).toHaveLength(1)
            expect(results[0].invocation.person?.properties).toEqual({ name: 'Person A 1' })

            // gRPC was attempted
            expect(failingGrpc.persons.fetchPersonsByDistinctIds).toHaveBeenCalled()
        })
    })
})
