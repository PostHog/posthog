import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PersonActorType, PropertyFilterType, PropertyOperator } from '~/types'

import { propertiesTimelineLogic } from './propertiesTimelineLogic'

const EXAMPLE_PERSON: PersonActorType = {
    type: 'person',
    id: '012e89b5-4239-4319-8ae4-d3cae2f5deb1',
    distinct_ids: ['one'],
    is_identified: true,
    properties: {},
    created_at: '2021-01-01T00:00:00.000Z',
    matched_recordings: [],
    value_at_data_point: null,
}

describe('propertiesTimelineLogic', () => {
    let logic: ReturnType<typeof propertiesTimelineLogic.build>
    const timelineRequest = jest.fn()

    beforeEach(() => {
        timelineRequest.mockClear()
        useMocks({
            get: {
                '/api/environments/:team_id/persons/:id/properties_timeline/': () => {
                    timelineRequest()
                    return [
                        200,
                        {
                            points: [
                                {
                                    timestamp: '2021-05-01T00:00:00.000Z',
                                    properties: { name: 'Gerry' },
                                    relevant_event_count: 1,
                                },
                            ],
                            crucial_property_keys: ['name'],
                            effective_date_from: '2021-01-01T00:00:00.000000+00:00',
                            effective_date_to: '2021-06-01T23:59:59.999999+00:00',
                        },
                    ]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('skips the request when the filter has no crucial person properties', async () => {
        // Query-based insights hand the modal a filter without person properties, so the backend would
        // scan the whole person timeline only to return "No key person properties".
        logic = propertiesTimelineLogic({
            actor: EXAMPLE_PERSON,
            filter: { date_from: '2021-01-01', date_to: '2021-06-01' },
        })
        logic.mount()
        await expectLogic(logic).toMatchValues({ resultLoading: false, result: null, crucialPropertyKeys: [] })
        expect(timelineRequest).not.toHaveBeenCalled()
    })

    it('loads the timeline when the filter includes a person property', async () => {
        logic = propertiesTimelineLogic({
            actor: EXAMPLE_PERSON,
            filter: {
                date_from: '2021-01-01',
                date_to: '2021-06-01',
                properties: [
                    { key: 'name', type: PropertyFilterType.Person, value: 'Gerry', operator: PropertyOperator.Exact },
                ],
            },
        })
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadResultSuccess'])
            .toMatchValues({ crucialPropertyKeys: ['name'] })
        expect(timelineRequest).toHaveBeenCalledTimes(1)
    })
})
