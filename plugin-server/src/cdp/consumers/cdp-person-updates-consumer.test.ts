import '../../../tests/helpers/mocks/producer.mock'

import { forSnapshot } from '~/tests/helpers/snapshots'

import { getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
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
        await resetTestDatabase()
        hub = await createHub({
            SITE_URL: 'http://localhost:8000',
        })
        team = await getFirstTeam(hub)

        processor = new CdpPersonUpdatesConsumer(hub)
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
                        "properties": {},
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
})
