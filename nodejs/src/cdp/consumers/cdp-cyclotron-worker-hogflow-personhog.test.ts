import { DateTime } from 'luxon'

import { HogFlow } from '~/schema/hogflow'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
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

    it('falls back to postgres and resolves person when gRPC is unavailable', async () => {
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

        const personhogRepo = new PersonHogPersonRepository(
            postgresPersonRepo,
            failingGrpc as unknown as PersonHogClient,
            100,
            'test'
        )
        const processor = new CdpCyclotronWorkerHogFlow(hub, {
            ...createCdpConsumerDeps(hub),
            personRepository: personhogRepo,
        })

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

        // gRPC was attempted and failed
        expect(failingGrpc.persons.fetchPersonsByDistinctIds).toHaveBeenCalled()
    })

    it('falls back to postgres for personId lookups when gRPC fails', async () => {
        const personUuid = 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1'
        await createPerson(team.id, personUuid, 'distinct_A_1', {
            name: 'Batch Person',
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

        const personhogRepo = new PersonHogPersonRepository(
            postgresPersonRepo,
            failingGrpc as unknown as PersonHogClient,
            100,
            'test'
        )
        const processor = new CdpCyclotronWorkerHogFlow(hub, {
            ...createCdpConsumerDeps(hub),
            personRepository: personhogRepo,
        })

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

        // gRPC was attempted for personId lookup
        expect(failingGrpc.persons.fetchPersonsByPersonIds).toHaveBeenCalled()
    })
})
