import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

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

function makePerson(teamId: number, uuid: string, distinctId: string, properties: Record<string, any>): InternalPerson {
    return {
        id: '42',
        uuid,
        team_id: teamId,
        properties,
        properties_last_updated_at: {},
        properties_last_operation: {},
        created_at: TIMESTAMP,
        version: 1,
        is_identified: true,
        is_user_id: null,
        last_seen_at: null,
    }
}

function createMockPersonReadRepository(
    overrides: Partial<jest.Mocked<PersonReadRepository>> = {}
): jest.Mocked<PersonReadRepository> {
    return {
        fetchPerson: jest.fn().mockResolvedValue(undefined),
        fetchPersonsByDistinctIds: jest.fn().mockResolvedValue([]),
        fetchPersonsByPersonIds: jest.fn().mockResolvedValue([]),
        fetchDistinctIdsForPersons: jest.fn().mockResolvedValue({}),
        ...overrides,
    }
}

describe('CdpCyclotronWorkerHogFlow with PersonHog', () => {
    let hub: Hub
    let team: Team
    let hogFlow: HogFlow

    const createSerializedHogFlowInvocation = (
        hf: HogFlow,
        _context: Partial<HogFlowInvocationContext> = {}
    ): CyclotronJobInvocation => {
        const context = createHogFlowInvocationContext(_context)
        return {
            id: new UUIDT().toString(),
            state: { ...context },
            teamId: hf.team_id,
            functionId: hf.id,
            queue: 'hogflow',
            queuePriority: 0,
        }
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub.postgres)

        hogFlow = await insertHogFlow(
            hub.postgres,
            new FixtureHogFlowBuilder()
                .withName('Test Hog Flow')
                .withTeamId(team.id)
                .withStatus('active')
                .withSimpleWorkflow()
                .build()
        )
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await closeHub(hub)
    })

    it('resolves person by distinct_id via personhog', async () => {
        const person = makePerson(team.id, 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1', 'distinct_A_1', {
            name: 'Person A 1',
        })

        const mockRepo = createMockPersonReadRepository({
            fetchPersonsByDistinctIds: jest.fn().mockResolvedValue([{ ...person, distinct_id: 'distinct_A_1' }]),
        })

        const mockJobQueue = createMockJobQueue()
        const processor = new CdpCyclotronWorkerHogFlow(
            hub,
            { ...createCdpConsumerDeps(hub), personRepository: mockRepo },
            mockJobQueue
        )

        const invocations = [
            createSerializedHogFlowInvocation(hogFlow, {
                event: { distinct_id: 'distinct_A_1', properties: { foo: 'bar' } } as any,
            }),
        ]

        const results = (await processor.processInvocations(
            invocations
        )) as CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]

        expect(results).toHaveLength(1)
        expect(results[0].invocation.person?.properties).toEqual({ name: 'Person A 1' })
        expect(mockRepo.fetchPersonsByDistinctIds).toHaveBeenCalled()
    })

    it('resolves person by personId via personhog', async () => {
        const personUuid = 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1'
        const person = makePerson(team.id, personUuid, 'distinct_A_1', {
            name: 'Batch Person',
        })

        const mockRepo = createMockPersonReadRepository({
            fetchPersonsByPersonIds: jest.fn().mockResolvedValue([person]),
            fetchDistinctIdsForPersons: jest.fn().mockResolvedValue({
                [person.id]: ['distinct_A_1'],
            }),
        })

        const mockJobQueue = createMockJobQueue()
        const processor = new CdpCyclotronWorkerHogFlow(
            hub,
            { ...createCdpConsumerDeps(hub), personRepository: mockRepo },
            mockJobQueue
        )

        const invocations = [
            createSerializedHogFlowInvocation(hogFlow, {
                event: { distinct_id: '', properties: { foo: 'batch' } } as any,
                personId: personUuid,
            }),
        ]

        const results = (await processor.processInvocations(
            invocations
        )) as CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]

        expect(results).toHaveLength(1)
        expect(results[0].invocation.person?.properties).toEqual({ name: 'Batch Person' })
        expect(results[0].invocation.person?.distinct_id).toBe('distinct_A_1')
        expect(results[0].invocation.state.event.distinct_id).toBe('distinct_A_1')
        expect(mockRepo.fetchPersonsByPersonIds).toHaveBeenCalled()
    })

    it('resolves person by personId (not the repointed distinct_id) when a merge re-keyed the job', async () => {
        // A person merge repointed this parked wait's distinct_id and re-keyed personId onto the survivor
        // (state.personIdRepointed). The survivor must be resolved by personId: resolving by the repointed
        // distinct_id hits its stale ~1min cache entry — the pre-merge person — so a downstream step (e.g.
        // an email) reads the wrong/empty properties and drops the send. Guards that regression.
        const survivorUuid = 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1'
        const survivor = makePerson(team.id, survivorUuid, 'survivor_did', {
            name: 'Survivor',
            email: 'survivor@example.com',
        })

        const mockRepo = createMockPersonReadRepository({
            // The distinct_id path would return the stale pre-merge person; personId returns the survivor.
            fetchPersonsByDistinctIds: jest
                .fn()
                .mockResolvedValue([makePerson(team.id, 'old-uuid', 'anon_did', { name: 'Pre-merge anon' })]),
            fetchPersonsByPersonIds: jest.fn().mockResolvedValue([survivor]),
            fetchDistinctIdsForPersons: jest.fn().mockResolvedValue({ [survivor.id]: ['survivor_did'] }),
        })

        const processor = new CdpCyclotronWorkerHogFlow(
            hub,
            { ...createCdpConsumerDeps(hub), personRepository: mockRepo },
            createMockJobQueue()
        )

        const invocations = [
            createSerializedHogFlowInvocation(hogFlow, {
                // The event still carries the anon distinct_id, but the re-key set personId + the flag.
                event: { distinct_id: 'anon_did', properties: {} } as any,
                personId: survivorUuid,
                personIdRepointed: true,
            }),
        ]

        const results = (await processor.processInvocations(
            invocations
        )) as CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]

        expect(results).toHaveLength(1)
        // Resolved the survivor (via personId), not the stale pre-merge person (via distinct_id).
        expect(results[0].invocation.person?.properties).toEqual({ name: 'Survivor', email: 'survivor@example.com' })
        expect(mockRepo.fetchPersonsByPersonIds).toHaveBeenCalled()
        expect(mockRepo.fetchPersonsByDistinctIds).not.toHaveBeenCalled()
    })

    it('clears personIdRepointed after the wake-resolution so later steps resolve by distinct_id again', async () => {
        // The flag is a one-shot override for the merge-wake resolution only. If it stuck around, a second
        // merge onto a non-wait step (out of the matcher's re-key scope) would leave the flow pinned to the
        // now-stale first survivor forever instead of self-healing via distinct_id. Guards that regression.
        const survivorUuid = 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1'
        const mockRepo = createMockPersonReadRepository({
            fetchPersonsByPersonIds: jest
                .fn()
                .mockResolvedValue([makePerson(team.id, survivorUuid, 'survivor_did', { name: 'Survivor' })]),
            fetchDistinctIdsForPersons: jest.fn().mockResolvedValue({ [survivorUuid]: ['survivor_did'] }),
        })

        const processor = new CdpCyclotronWorkerHogFlow(
            hub,
            { ...createCdpConsumerDeps(hub), personRepository: mockRepo },
            createMockJobQueue()
        )

        const results = (await processor.processInvocations([
            createSerializedHogFlowInvocation(hogFlow, {
                event: { distinct_id: 'anon_did', properties: {} } as any,
                personId: survivorUuid,
                personIdRepointed: true,
            }),
        ])) as CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]

        expect(results[0].invocation.state.personIdRepointed).toBeUndefined()
    })

    it('propagates error when personhog is unavailable', async () => {
        const mockRepo = createMockPersonReadRepository({
            fetchPersonsByDistinctIds: jest.fn().mockRejectedValue(new Error('gRPC unavailable')),
        })

        const mockJobQueue = createMockJobQueue()
        const processor = new CdpCyclotronWorkerHogFlow(
            hub,
            { ...createCdpConsumerDeps(hub), personRepository: mockRepo },
            mockJobQueue
        )

        const invocations = [
            createSerializedHogFlowInvocation(hogFlow, {
                event: { distinct_id: 'distinct_A_1', properties: { foo: 'bar' } } as any,
            }),
        ]

        await expect(processor.processInvocations(invocations)).rejects.toThrow('gRPC unavailable')
    })
})
