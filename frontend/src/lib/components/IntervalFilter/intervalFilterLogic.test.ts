import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'

import { BaseMathType, InsightShortId } from '~/types'

import { useMocks } from '~/mocks/jest'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { intervalFilterLogic } from './intervalFilterLogic'
import { TrendsQuery } from '~/queries/schema'

const Insight123 = '123' as InsightShortId

describe('intervalFilterLogic', () => {
    let builtInsightVizDataLogic: ReturnType<typeof insightVizDataLogic.build>
    let builtIntervalFilterLogic: ReturnType<typeof intervalFilterLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/insights/trend': [],
            },
        })
        initKeaTests()

        const props = { dashboardItemId: Insight123 }

        builtInsightVizDataLogic = insightVizDataLogic(props)
        builtIntervalFilterLogic = intervalFilterLogic(props)

        builtInsightVizDataLogic.mount()
        builtIntervalFilterLogic.mount()
    })

    describe('enabledIntervals', () => {
        it('returns all intervals', () => {
            expectLogic(builtIntervalFilterLogic).toMatchValues({
                enabledIntervals: {
                    day: { label: 'day', newDateFrom: undefined },
                    hour: { label: 'hour', newDateFrom: 'dStart' },
                    month: { label: 'month', newDateFrom: '-90d' },
                    week: { label: 'week', newDateFrom: '-30d' },
                },
            })
        })

        it('adds a disabled reason with active users math', () => {
            expectLogic(builtIntervalFilterLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: 'EventsNode',
                            name: '$pageview',
                            event: '$pageview',
                            math: BaseMathType.WeeklyActiveUsers,
                        },
                    ],
                } as Partial<TrendsQuery>)
            }).toMatchValues({
                enabledIntervals: {
                    day: { label: 'day', newDateFrom: undefined },
                    hour: {
                        label: 'hour',
                        newDateFrom: 'dStart',
                        disabledReason:
                            'Grouping by hour is not supported on insights with weekly or monthly active users series.',
                    },
                    month: {
                        label: 'month',
                        newDateFrom: '-90d',
                        disabledReason:
                            'Grouping by month is not supported on insights with weekly active users series.',
                    },
                    week: { label: 'week', newDateFrom: '-30d' },
                },
            })
        })
    })
})
