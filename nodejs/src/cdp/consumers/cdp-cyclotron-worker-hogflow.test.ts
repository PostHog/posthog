import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { InternalPersonWithDistinctId, PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { createTeam, createTestTeamFixture, getTeam } from '~/tests/helpers/sql'

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
        hub = await createHub()
        const { organizationId, team: fixtureTeam } = await createTestTeamFixture(hub.postgres)
        team = fixtureTeam
        const team2Id = await createTeam(hub.postgres, organizationId)
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

        hogFlows.push(
            await insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withName('Test Hog Flow with a wait')
                    .withTeamId(team.id)
                    .withStatus('active')
                    .withWorkflow({
                        actions: {
                            trigger: {
                                type: 'trigger',
                                config: { type: 'event', filters: {} },
                            },
                            wait: {
                                type: 'wait_until_condition',
                                config: {
                                    condition: { filters: { properties: [{ key: 'email', type: 'person' }] } },
                                    max_wait_duration: '1h',
                                } as any,
                            },
                            exit: { type: 'exit', config: {} },
                        },
                        edges: [
                            { from: 'trigger', to: 'wait', type: 'continue' },
                            { from: 'wait', to: 'exit', type: 'continue' },
                        ],
                    } as any)
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

        it('persists the resolved person UUID into state so a re-parked wait keeps its person_id', async () => {
            const results = (await processor.processInvocations(
                invocations
            )) as CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]

            // invocation1 (distinct_A_1) resolves to Person A 1 — its UUID is written back into
            // state.personId, so a later re-park keeps person_id even if re-resolution transiently misses.
            // clickhouse_person wakes match on person_id only, so this is what lets a person-property
            // change wake the wait without relying on the polling backstop.
            expect(results[0].invocation.state.personId).toBe('dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1')
            // invocation4 (missing_person) resolves to nothing — no person_id to persist.
            expect(results[3].invocation.state.personId).toBeUndefined()
        })

        it('supplies a refreshPerson hook that re-reads uncached and rebuilds the filter globals', async () => {
            // A wait step calls this before its first evaluation. Without it the wait evaluates the
            // person the dequeue cached, and a run that parks on a stale read has nothing left to wake it.
            const results = (await processor.processInvocations([
                createSerializedHogFlowInvocation(hogFlows[2], {
                    event: { distinct_id: 'distinct_A_1', properties: {} } as any,
                }),
            ])) as CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]

            const getPerson = jest.spyOn(processor['personsManager'], 'getCyclotronPerson').mockResolvedValue({
                id: 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1',
                properties: { name: 'Person A 1', email: 'written-after-caching@posthog.com' },
                name: 'Person A 1',
                url: 'http://localhost:8000/project/1/person/distinct_A_1',
                distinct_id: 'distinct_A_1',
            })

            const refreshed = await results[0].invocation.refreshPerson!()

            expect(getPerson).toHaveBeenCalledWith(expect.any(Number), 'distinct_A_1', 'distinct_id', {
                forceFresh: true,
            })
            expect(refreshed.filterGlobals.person?.properties).toEqual({
                name: 'Person A 1',
                email: 'written-after-caching@posthog.com',
            })
        })

        it('terminates invocations as canceled when the workflow is disabled after being queued', async () => {
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

            // Second batch: invocation2 wakes under a disabled workflow. It must terminate
            // through the result pipeline (terminal row, metric, log): a silent queue-side
            // flip would leave the run showing 'running' in the Invocations UI forever.
            const results2 = await processor.processInvocations([invocation2])

            expect(results2).toHaveLength(1)
            expect(results2[0].finished).toBe(true)
            expect(results2[0].canceled).toBe(true)
            expect(results2[0].error).toBeUndefined()
            expect(results2[0].logs.map((l) => l.message)).toContain('Run canceled: the workflow is no longer active')
            expect(results2[0].metrics).toEqual([
                expect.objectContaining({
                    team_id: hogFlow.team_id,
                    app_source_id: hogFlow.id,
                    metric_kind: 'other',
                    metric_name: 'canceled',
                    count: 1,
                }),
            ])
            // The flow must ride along on the canceled result: the monitoring services key the
            // terminal lifecycle row off its presence, so without it the row keys `hog_function`,
            // never collapses the `running` row, and the run stays stuck at `running` in the UI.
            expect((results2[0].invocation as CyclotronJobInvocationHogFlow).hogFlow?.id).toBe(hogFlow.id)
        })

        it('attaches the live flow to a cancel-requested run so the terminal row keys as hog_flow', async () => {
            const hogFlow = hogFlows[0]
            const invocation = createSerializedHogFlowInvocation(hogFlow, {
                event: { distinct_id: 'distinct_person_1', properties: { foo: 'bar1' } } as any,
            })
            invocation.cancelRequestedAt = DateTime.now()

            const results = await processor.processInvocations([invocation])

            expect(results).toHaveLength(1)
            expect(results[0].finished).toBe(true)
            expect(results[0].canceled).toBe(true)
            expect((results[0].invocation as CyclotronJobInvocationHogFlow).hogFlow?.id).toBe(hogFlow.id)
        })

        it('terminates cancel-requested invocations without loading the flow, so cancel works for deleted flows', async () => {
            const invocation = createSerializedHogFlowInvocation(hogFlows[0], {
                event: {
                    distinct_id: 'distinct_A_1',
                    properties: { foo: 'bar1' },
                } as any,
            })
            invocation.functionId = new UUIDT().toString() // flow no longer exists
            invocation.cancelRequestedAt = DateTime.now()

            const results = await processor.processInvocations([invocation])

            expect(results).toHaveLength(1)
            expect(results[0].finished).toBe(true)
            expect(results[0].canceled).toBe(true)
            expect(results[0].logs.map((l) => l.message)).toContain('Run canceled')
            expect(results[0].metrics).toEqual([
                expect.objectContaining({ metric_name: 'canceled', metric_kind: 'other', count: 1 }),
            ])
            // Even with no flow to load, the canceled result must still carry the flow id so the
            // invocation keys the terminal lifecycle row as `hog_flow` (not `hog_function`) and
            // collapses the earlier `running` row instead of leaving the run stuck at `running`.
            expect((results[0].invocation as CyclotronJobInvocationHogFlow).hogFlow?.id).toBe(invocation.functionId)
        })
    })
})
