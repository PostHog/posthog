import '../helpers/mocks/producer.mock'

import { CdpInternalEventsConsumer } from '../../../src/cdp/consumers/cdp-internal-events.consumer'
import { HogFunctionType } from '../../../src/cdp/types'
import { Hub, Team } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { getFirstTeam, resetTestDatabase } from '../../helpers/sql'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../examples'
import { createInternalEvent, createKafkaMessage, insertHogFunction as _insertHogFunction } from '../fixtures'

describe('CDP Internal Events Consumer', () => {
    let processor: CdpInternalEventsConsumer
    let hub: Hub
    let team: Team

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const item = await _insertHogFunction(hub.postgres, team.id, hogFunction)
        // Trigger the reload that django would do
        await processor.hogFunctionManager.reloadAllHogFunctions()
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)

        processor = new CdpInternalEventsConsumer(hub)
        await processor.start()
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
            const events = await processor._parseKafkaBatch([createKafkaMessage(createInternalEvent(999999, {}))])
            expect(events).toHaveLength(0)
        })

        describe('with an existing team and hog function', () => {
            beforeEach(async () => {
                await insertHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.no_filters,
                    type: 'internal_destination',
                })
            })

            it('should ignore invalid payloads', async () => {
                const events = await processor._parseKafkaBatch([
                    createKafkaMessage(
                        createInternalEvent(team.id, {
                            event: 'WRONG' as any,
                        })
                    ),
                ])
                expect(events).toHaveLength(0)
            })

            it('should parse a valid message with an existing team and hog function ', async () => {
                const event = createInternalEvent(team.id, {})
                event.event.timestamp = '2024-12-18T15:06:23.545Z'
                event.event.uuid = 'b6da2f33-ba54-4550-9773-50d3278ad61f'

                const events = await processor._parseKafkaBatch([createKafkaMessage(event)])
                expect(events).toHaveLength(1)
                expect(events[0]).toEqual({
                    event: {
                        distinct_id: 'distinct_id',
                        elements_chain: '',
                        event: '$pageview',
                        properties: {},
                        timestamp: '2024-12-18T15:06:23.545Z',
                        url: '',
                        uuid: 'b6da2f33-ba54-4550-9773-50d3278ad61f',
                    },
                    person: undefined,
                    project: {
                        id: 2,
                        name: 'TEST PROJECT',
                        url: 'http://localhost:8000/project/2',
                    },
                })
            })
        })
    })
})
