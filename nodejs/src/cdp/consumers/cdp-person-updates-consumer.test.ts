import { createMockJobQueue } from '../../../tests/helpers/mocks/job-queue.mock'
import '../../../tests/helpers/mocks/producer.mock'

import { closeHub, createHub } from '~/common/utils/db/hub'
import { forSnapshot } from '~/tests/helpers/snapshots'

import { createCdpConsumerDeps } from '../../../tests/helpers/cdp'
import { getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { ClickHousePerson, Hub, Team } from '../../types'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import {
    insertHogFunction as _insertHogFunction,
    createClickhousePerson,
    createHogFunction,
    createKafkaMessage,
} from '../_tests/fixtures'
import { insertHogFlow as _insertHogFlow } from '../_tests/fixtures-hogflows'
import { HogFunctionType } from '../types'
import { CdpPersonUpdatesConsumer } from './cdp-person-updates-consumer'

describe('CDP Person Updates Consumer', () => {
    let processor: CdpPersonUpdatesConsumer
    let hub: Hub
    let team: Team
    let hogFunction: HogFunctionType

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const item = await _insertHogFunction(hub.postgres, team.id, hogFunction)
        // Trigger the reload that django would do
        processor['hogFunctionManager']['onHogFunctionsReloaded'](team.id, [item.id])
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub({
            SITE_URL: 'http://localhost:8000',
        })
        team = await getFirstTeam(hub.postgres)

        processor = new CdpPersonUpdatesConsumer(hub, createCdpConsumerDeps(hub), {
            hogQueue: createMockJobQueue(),
            hogflowQueue: createMockJobQueue(),
        })
        await processor.start()

        hogFunction = createHogFunction({
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
        })

        hogFunction.filters = { ...hogFunction.filters, source: 'person-updates' }
        await insertHogFunction(hogFunction)
    })

    afterEach(async () => {
        await processor.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('_handleKafkaBatch', () => {
        it('should ignore invalid message', async () => {
            const events = await processor._parseKafkaBatch([createKafkaMessage({})])
            expect(events).toHaveLength(0)
        })

        it('should ignore message with no team', async () => {
            const events = await processor._parseKafkaBatch([createKafkaMessage(createClickhousePerson(999999, {}))])
            expect(events).toHaveLength(0)
        })
        it('should parse a valid message with an existing team and hog function ', async () => {
            const event = createClickhousePerson(team.id, {
                id: 'person-id-1',
            })

            event.timestamp = '2025-01-01T01:01:01.000Z'

            const events = await processor._parseKafkaBatch([createKafkaMessage(event)])
            expect(events).toHaveLength(1)
            expect(forSnapshot(events[0])).toMatchInlineSnapshot(`
                    {
                      "event": {
                        "distinct_id": "person-id-1",
                        "elements_chain": "",
                        "event": "$person_updated",
                        "properties": {
                          "$person_deleted": false,
                        },
                        "timestamp": "2025-01-01T01:01:01.000Z",
                        "url": "http://localhost:8000/project/2/person/person-id-1",
                        "uuid": "<REPLACED-UUID-0>",
                      },
                      "person": {
                        "id": "person-id-1",
                        "name": "person-id-1",
                        "properties": {
                          "email": "test@posthog.com",
                        },
                        "url": "http://localhost:8000/project/2/person/person-id-1",
                      },
                      "project": {
                        "id": 2,
                        "name": "TEST PROJECT",
                        "url": "http://localhost:8000/project/2",
                      },
                    }
                `)
        })
    })

    describe('processing', () => {
        it('should only run hog functions that are filtering for person updates', async () => {
            const hogFunctionEvents = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
                type: 'destination',
            })

            await insertHogFunction(hogFunctionEvents)

            const events = await processor._parseKafkaBatch([createKafkaMessage(createClickhousePerson(team.id, {}))])
            const result = await processor.processBatch(events)

            expect(result.invocations).toHaveLength(1)
            expect(result.invocations[0].functionId).toEqual(hogFunction.id)
        })
    })

    describe('workflows', () => {
        const insertPersonUpdatesHogFlow = async (includeDeleted?: boolean) =>
            await _insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'person-updates',
                            filters: { properties: [], bytecode: ['_h', 29] } as any,
                            ...(includeDeleted === undefined ? {} : { include_deleted: includeDeleted }),
                        },
                    })
                    .build()
            )

        const processPerson = async (data: Partial<ClickHousePerson>) => {
            const events = await processor._parseKafkaBatch([createKafkaMessage(createClickhousePerson(team.id, data))])
            const { invocations } = await processor.processBatch(events)
            return invocations.filter((invocation: any) => invocation.hogFlow)
        }

        it('anchors the run on the person id, which is all a later step can resolve by', async () => {
            const hogFlow = await insertPersonUpdatesHogFlow()

            const invocations = await processPerson({ id: 'person-id-1' })

            expect(invocations).toHaveLength(1)
            expect(invocations[0].functionId).toEqual(hogFlow.id)
            expect((invocations[0] as any).state.personId).toEqual('person-id-1')
        })

        it.each([
            ['skips a deletion by default', undefined, 1, 0],
            ['runs on a deletion when opted in', true, 1, 1],
            ['runs on an update when deletions are opted out', false, 0, 1],
        ])('%s', async (_name, includeDeleted, isDeleted, expected) => {
            await insertPersonUpdatesHogFlow(includeDeleted)

            expect(await processPerson({ is_deleted: isDeleted })).toHaveLength(expected)
        })
    })
})
