import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { NodeKind, TrendsQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { buildTrendsQuery } from '~/test/insight-testing'
import { ChartDisplayType, InsightShortId } from '~/types'

import { changeChartLogic } from './changeChartLogic'

jest.mock('scenes/trends/persons-modal/PersonsModal')

const insightProps = { dashboardItemId: 'change-chart-logic' as InsightShortId }

const response = {
    results: [
        {
            action: { id: '$pageview', type: 'events', name: '$pageview', order: 0 },
            label: '$pageview',
            count: 100,
            aggregated_value: 100,
            data: [],
            days: [],
            labels: [],
            breakdown_value: 'New York',
            compare: true,
            compare_label: 'current',
        },
        {
            action: { id: '$pageview', type: 'events', name: '$pageview', order: 0 },
            label: '$pageview',
            count: 80,
            aggregated_value: 80,
            data: [],
            days: [],
            labels: [],
            breakdown_value: 'New York',
            compare: true,
            compare_label: 'previous',
        },
    ],
    resolved_date_range: {
        date_from: '2025-01-08T00:00:00Z',
        date_to: '2025-01-15T00:00:00Z',
    },
} as TrendsQueryResponse

describe('changeChartLogic', () => {
    beforeEach(() => {
        initKeaTests()
        insightLogic(insightProps).mount()
        insightDataLogic(insightProps).mount()

        const vizLogic = insightVizDataLogic(insightProps)
        vizLogic.mount()
        vizLogic.actions.updateQuerySource(
            buildTrendsQuery({
                dateRange: { date_from: '-7d', explicitDate: true },
                breakdownFilter: { breakdown: '$browser' },
                compareFilter: { compare: true },
                trendsFilter: { display: ChartDisplayType.ChangeChart },
            })
        )
        vizLogic.actions.setInsightData(response)
    })

    it('builds display rows and period labels from logic state', () => {
        const logic = changeChartLogic({ insightProps, showPersonsModal: true })
        logic.mount()

        expect(logic.values.changeChartDisplayRows).toHaveLength(1)
        expect(logic.values.changeChartDisplayRows[0]).toMatchObject({
            label: 'New York',
            metricLabel: '$pageview',
            currentValueLabel: '100',
            previousValueLabel: '80',
            changeLabel: '+25%',
        })
        expect(logic.values.axisLabels).toEqual(['-40%', '-20%', '0%', '20%', '40%'])
        expect(logic.values.currentPeriodLabel).toContain('Jan 8')
        expect(logic.values.previousPeriodLabel).toContain('Jan 1')
    })

    it('opens the persons modal from the logic listener', () => {
        const logic = changeChartLogic({ insightProps, showPersonsModal: true })
        logic.mount()

        logic.actions.openRow(logic.values.changeChartDisplayRows[0])

        expect(openPersonsModal).toHaveBeenCalledWith(
            expect.objectContaining({
                title: 'New York',
                query: expect.objectContaining({
                    kind: NodeKind.InsightActorsQuery,
                    breakdown: 'New York',
                    compare: 'current',
                }),
            })
        )
    })
})
