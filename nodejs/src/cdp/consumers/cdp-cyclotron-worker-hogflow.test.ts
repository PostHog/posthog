import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { InternalPersonWithDistinctId, PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { createTeam, getFirstTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, InternalPerson, Team } from '../../types'
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

const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()

type TestPerson = {
    id: string
    uuid: string
    teamId: number
    distinctId: string
    properties: Record<string, any>
}

function toInternalPerson(p: TestPerson): InternalPerson {
    return {
        id: p.id,
        uuid: p.uuid,
        team_id: p.teamId,
        properties: p.properties,
        properties_last_updated_at: {},
        properties_last_operation: null,
        created_at: TIMESTAMP,
        version: 1,
        is_identified: true,
        is_user_id: null,
        last_seen_at: null,
    }
}

function createMockPersonReadRepository(persons: TestPerson[]): jest.Mocked<PersonReadRepository> {
    return {
        fetchPerson: jest.fn().mockImplementation((teamId: number, distinctId: string) => {
            const match = persons.find((p) => p.teamId === teamId && p.distinctId === distinctId)
            return Promise.resolve(match ? toInternalPerson(match) : undefined)
        }),
        fetchPersonsByDistinctIds: jest
            .fn()
            .mockImplementation((teamPersons: { teamId: number; distinctId: string }[]) => {
                const results: InternalPersonWithDistinctId[] = persons
                    .filter((p) => teamPersons.some((tp) => tp.teamId === p.teamId && tp.distinctId === p.distinctId))
                    .map((p) => ({ ...toInternalPerson(p), distinct_id: p.distinctId }))
                return Promise.resolve(results)
            }),
        fetchPersonsByPersonIds: jest.fn().mockImplementation((teamPersons: { teamId: number; personId: string }[]) => {
            const results: InternalPerson[] = persons
                .filter((p) => teamPersons.some((tp) => tp.teamId === p.teamId && tp.personId === p.uuid))
                .map(toInternalPerson)
            return Promise.resolve(results)
        }),
        fetchDistinctIdsForPersons: jest.fn().mockImplementation((teamId: number, personIntIds: string[]) => {
            const result: Record<string, string[]> = {}
            for (const intId of personIntIds) {
                const match = persons.find((p) => p.teamId === teamId && p.id === intId)
                if (match) {
                    result[intId] = [match.distinctId]
                }
            }
            return Promise.resolve(result)
        }),
    }
}

describe('CdpCyclotronWorkerHogFlow', () => {
    let processor: CdpCyclotronWorkerHogFlow
    let hub: Hub
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
            state: {
                ...context,
            },
            teamId: hogFlow.team_id,
            functionId: hogFlow.id,
            queue: 'hogflow',
            queuePriority: 0,
        }
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub.postgres)
        const team2Id = await createTeam(hub.postgres, team.organization_id)
        team2 = (await getTeam(hub.postgres, team2Id))!

        const testPersons: TestPerson[] = [
            {
                id: '1',
                uuid: 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1',
                teamId: team.id,
                distinctId: 'distinct_A_1',
                properties: { name: 'Person A 1' },
            },
            {
                id: '2',
                uuid: 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e2',
                teamId: team.id,
                distinctId: 'distinct_A_2',
                properties: { name: 'Person A 2' },
            },
            {
                id: '3',
                uuid: 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e3',
                teamId: team2.id,
                distinctId: 'distinct_A_1',
                properties: { name: 'Person A 3' },
            },
            {
                id: '4',
                uuid: 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7f0',
                teamId: team.id,
                distinctId: 'distinct_batch_1',
                properties: { name: 'Batch Person', email: 'batch@posthog.com' },
            },
            {
                id: '5',
                uuid: 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e4',
                teamId: team.id,
                distinctId: 'distinct_person_1',
                properties: { name: 'Person 1' },
            },
            {
                id: '6',
                uuid: 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e5',
                teamId: team.id,
                distinctId: 'distinct_person_2',
                properties: { name: 'Person 2' },
            },
        ]

        const mockRepo = createMockPersonReadRepository(testPersons)
        const mockJobQueue = createMockJobQueue()
        processor = new CdpCyclotronWorkerHogFlow(
            hub,
            { ...createCdpConsumerDeps(hub), personRepository: mockRepo },
            mockJobQueue
        )

        hogFlows = []
        hogFlows.push(
            await insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withName('Test Hog Flow team 2')
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

    describe('loadHogFlows', () => {
        let invocations: CyclotronJobInvocation[]

        beforeEach(() => {
            const invocation1 = createSerializedHogFlowInvocation(hogFlows[0], {
                event: {
                    distinct_id: 'distinct_A_1',
                    properties: {
                        foo: 'bar1',
                    },
                } as any,
            })
            const invocation2 = createSerializedHogFlowInvocation(hogFlows[0], {
                event: {
                    distinct_id: 'distinct_A_2',
                    properties: {
                        foo: 'bar2',
                    },
                } as any,
            })
            const invocation3 = createSerializedHogFlowInvocation(hogFlows[1], {
                event: {
                    distinct_id: 'distinct_A_1', // Same distinct_id but different hog flow
                    properties: {
                        foo: 'bar3',
                    },
                } as any,
            })
            const invocation4 = createSerializedHogFlowInvocation(hogFlows[1], {
                event: {
                    distinct_id: 'missing_person', // Missing person
                    properties: {
                        foo: 'bar4',
                    },
                } as any,
            })

            invocations = [invocation1, invocation2, invocation3, invocation4]
        })

        it('should load hog flows and their persons and globals', async () => {
            const results = (await processor.processInvocations(
                invocations
            )) as CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]

            const toMinimalCompare = (
                result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>
            ): Record<string, unknown> => {
                return {
                    hogFlowName: result.invocation.hogFlow.name,
                    filterGlobals: result.invocation.filterGlobals
                        ? {
                              eventProperties: result.invocation.filterGlobals.properties,
                              person: result.invocation.filterGlobals.person,
                          }
                        : null,
                    personName: result.invocation.person?.properties?.name,
                }
            }

            // Check all hog functions were loaded
            expect(results.map(toMinimalCompare)).toMatchInlineSnapshot(`
                [
                  {
                    "filterGlobals": {
                      "eventProperties": {
                        "foo": "bar1",
                      },
                      "person": {
                        "id": "dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1",
                        "properties": {
                          "name": "Person A 1",
                        },
                      },
                    },
                    "hogFlowName": "Test Hog Flow team 2",
                    "personName": "Person A 1",
                  },
                  {
                    "filterGlobals": {
                      "eventProperties": {
                        "foo": "bar2",
                      },
                      "person": {
                        "id": "dd3d6f80-60ad-45c3-bd61-e2300f2ba7e2",
                        "properties": {
                          "name": "Person A 2",
                        },
                      },
                    },
                    "hogFlowName": "Test Hog Flow team 2",
                    "personName": "Person A 2",
                  },
                  {
                    "filterGlobals": {
                      "eventProperties": {
                        "foo": "bar3",
                      },
                      "person": {
                        "id": "dd3d6f80-60ad-45c3-bd61-e2300f2ba7e3",
                        "properties": {
                          "name": "Person A 3",
                        },
                      },
                    },
                    "hogFlowName": "Test Hog Flow team 2",
                    "personName": "Person A 3",
                  },
                  {
                    "filterGlobals": {
                      "eventProperties": {
                        "foo": "bar4",
                      },
                      "person": null,
                    },
                    "hogFlowName": "Test Hog Flow team 2",
                    "personName": undefined,
                  },
                ]
            `)
        })

        it('should make minimal calls to the person manager', async () => {
            const personManagerSpy = jest.spyOn(processor['personsManager'] as any, 'fetchPersonsByDistinctIds')
            await processor.processInvocations(invocations)
            expect(personManagerSpy).toHaveBeenCalledTimes(1)
            expect(personManagerSpy.mock.calls[0][0]).toEqual([
                `${team.id}:distinct_A_1`,
                `${team.id}:distinct_A_2`,
                `${team2.id}:distinct_A_1`,
                `${team2.id}:missing_person`,
            ])
        })

        it('should resolve person by personId when distinct_id is empty (batch invocations)', async () => {
            const personUuid = 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7f0'

            // Batch invocations set distinct_id: '' and use personId instead
            const invocation = createSerializedHogFlowInvocation(hogFlows[0], {
                event: {
                    distinct_id: '',
                    properties: { foo: 'batch' },
                } as any,
                personId: personUuid,
            })

            const results = (await processor.processInvocations([
                invocation,
            ])) as CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]

            expect(results).toHaveLength(1)
            expect(results[0].invocation.person?.properties).toEqual({
                name: 'Batch Person',
                email: 'batch@posthog.com',
            })
            expect(results[0].invocation.filterGlobals?.person?.id).toBe(personUuid)
        })

        it('should skip invocations when workflow is disabled after being queued', async () => {
            const hogFlow = hogFlows[0]

            const invocation1 = createSerializedHogFlowInvocation(hogFlow, {
                event: {
                    distinct_id: 'distinct_person_1',
                    properties: { foo: 'bar1' },
                } as any,
            })

            const invocation2 = createSerializedHogFlowInvocation(hogFlow, {
                event: {
                    distinct_id: 'distinct_person_2',
                    properties: { foo: 'bar2' },
                } as any,
            })

            // First batch: process invocation1 while workflow is active
            const results1 = (await processor.processInvocations([
                invocation1,
            ])) as CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]

            expect(results1).toHaveLength(1)
            expect(results1[0].invocation.filterGlobals?.properties?.foo).toBe('bar1')

            // Now disable the workflow (simulate user archiving it)
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_hogflow SET status = 'archived' WHERE id = $1`,
                [hogFlow.id],
                'disableHogFlow'
            )

            // Mark the hogflow for refresh so it fetches fresh data
            ;(processor['hogFlowManager'] as any)['lazyLoader'].markForRefresh(hogFlow.id)

            // Mock cancelInvocations to track what gets skipped
            const cancelInvocationsSpy = jest.spyOn(processor['cyclotronJobQueue'], 'cancelInvocations')

            // Second batch: invocation2 should be skipped because workflow is now disabled
            const results2 = (await processor.processInvocations([
                invocation2,
            ])) as CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]

            // No results because the workflow is disabled
            expect(results2).toHaveLength(0)

            // The invocation should have been canceled (not failed)
            expect(cancelInvocationsSpy).toHaveBeenCalledWith([invocation2])
        })
    })
})
