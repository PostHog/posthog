import '../../../tests/helpers/mocks/consumer.mock'
import { createMockJobQueue } from '../../../tests/helpers/mocks/job-queue.mock'
import '../../../tests/helpers/mocks/producer.mock'

import { closeHub, createHub } from '~/common/utils/db/hub'
import { forSnapshot } from '~/tests/helpers/snapshots'

import { createCdpConsumerDeps } from '../../../tests/helpers/cdp'
import { createTestTeamFixture } from '../../../tests/helpers/sql'
import { Hub, Team } from '../../types'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import {
    insertHogFunction as _insertHogFunction,
    createClickhousePerson,
    createHogFunction,
    createKafkaMessage,
} from '../_tests/fixtures'
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
        hub = await createHub({
            SITE_URL: 'http://localhost:8000',
        })
        team = (await createTestTeamFixture(hub.postgres)).team

        const mockJobQueue = createMockJobQueue()
        processor = new CdpPersonUpdatesConsumer(hub, createCdpConsumerDeps(hub), mockJobQueue)
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
            const snapshot = forSnapshot(events[0])
            snapshot.event.url = '<TEAM_URL>'
            snapshot.person.url = '<TEAM_URL>'
            snapshot.project.id = '<TEAM_ID>'
            snapshot.project.url = '<TEAM_URL>'
            expect(snapshot).toMatchInlineSnapshot(`
                    {
                      "event": {
                        "distinct_id": "person-id-1",
                        "elements_chain": "",
                        "event": "$person_updated",
                        "properties": {},
                        "timestamp": "2025-01-01T01:01:01.000Z",
                        "url": "<TEAM_URL>",
                        "uuid": "<REPLACED-UUID-0>",
                      },
                      "person": {
                        "id": "person-id-1",
                        "name": "person-id-1",
                        "properties": {
                          "email": "test@posthog.com",
                        },
                        "url": "<TEAM_URL>",
                      },
                      "project": {
                        "id": "<TEAM_ID>",
                        "name": "TEST PROJECT",
                        "url": "<TEAM_URL>",
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
})
