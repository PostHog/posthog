import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { personsModalLogic } from './personsModalLogic'

describe('personsModalLogic', () => {
    let logic: ReturnType<typeof personsModalLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                'api/environments/:team_id/persons/trends': {},
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('propertiesTimelineFilterFromUrl selector', () => {
        it('extract only the relevant properties from URL', async () => {
            logic = personsModalLogic({
                url: '/api/projects/1/persons/trends/?breakdown_attribution_type=first_touch&breakdown_normalize_url=False&date_from=2022-12-01T00%3A00%3A00%2B00%3A00&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%7B%7D%7D%5D&insight=TRENDS&interval=day&properties=%7B%22type%22%3A+%22AND%22%2C+%22values%22%3A+%5B%7B%22key%22%3A+%22id%22%2C+%22type%22%3A+%22precalculated-cohort%22%2C+%22value%22%3A+6%7D%5D%7D&smoothing_intervals=1&entity_id=%24pageview&entity_type=events&date_to=2022-12-13T00%3A00%3A00%2B00%3A00&entity_order=0&include_recordings=true',
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                propertiesTimelineFilterFromUrl: {
                    date_from: '2022-12-01T00:00:00+00:00',
                    date_to: '2022-12-13T00:00:00+00:00',
                    display: 'ActionsLineGraph',
                    insight: 'TRENDS',
                    interval: 'day',
                    events: [
                        {
                            custom_name: null,
                            id: '$pageview',
                            math: null,
                            math_group_type_index: null,

                            math_property: null,
                            name: '$pageview',
                            order: 0,
                            properties: {},
                            type: 'events',
                        },
                    ],
                    properties: {
                        type: 'AND',
                        values: [
                            {
                                key: 'id',
                                type: 'precalculated-cohort',
                                value: 6,
                            },
                        ],
                    },
                },
            })
        })
    })
})
