import { kea } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import type { funnelLogicType } from './funnelLogicType'
import {
    FunnelCorrelation,
    FunnelCorrelationResultsType,
    FunnelsFilterType,
    FunnelStep,
    FunnelStepWithConversionMetrics,
    InsightLogicProps,
} from '~/types'

import {
    getBreakdownStepValues,
    generateBaselineConversionUrl,
    parseBreakdownValue,
    parseEventAndProperty,
} from './funnelUtils'
import { isFunnelsFilter, keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { funnelTitle } from 'scenes/trends/persons-modal/persons-modal-utils'

export type OpenPersonsModelProps = {
    step: FunnelStep
    stepIndex?: number
    converted: boolean
}

export const funnelLogic = kea<funnelLogicType>({
    path: (key) => ['scenes', 'funnels', 'funnelLogic', key],
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('insight_funnel'),

    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters as inflightFilters', 'isInDashboardContext']],
    }),

    actions: () => ({
        openPersonsModalForStep: ({ step, stepIndex, converted }: OpenPersonsModelProps) => ({
            step,
            stepIndex,
            converted,
        }),
        openPersonsModalForSeries: ({
            step,
            series,
            converted,
        }: {
            step: FunnelStep
            series: Omit<FunnelStepWithConversionMetrics, 'nested_breakdown'>
            converted: boolean
        }) => ({
            step,
            series,
            converted,
        }),

        showTooltip: (
            origin: [number, number, number],
            stepIndex: number,
            series: FunnelStepWithConversionMetrics
        ) => ({
            origin,
            stepIndex,
            series,
        }),
        hideTooltip: true,

        // Correlation related actions
        openCorrelationPersonsModal: (correlation: FunnelCorrelation, success: boolean) => ({
            correlation,
            success,
        }),
    }),
    reducers: () => ({
        isTooltipShown: [
            false,
            {
                showTooltip: () => true,
                hideTooltip: () => false,
            },
        ],
        currentTooltip: [
            null as [number, FunnelStepWithConversionMetrics] | null,
            {
                showTooltip: (_, { stepIndex, series }) => [stepIndex, series],
            },
        ],
        tooltipOrigin: [
            null as [number, number, number] | null, // x, y, width
            {
                showTooltip: (_, { origin }) => origin,
            },
        ],
    }),

    selectors: () => ({
        filters: [
            (s) => [s.inflightFilters],
            (inflightFilters): Partial<FunnelsFilterType> =>
                inflightFilters && isFunnelsFilter(inflightFilters) ? inflightFilters : {},
        ],
        disableFunnelBreakdownBaseline: [
            () => [(_, props) => props],
            (props: InsightLogicProps): boolean => !!props.cachedInsight?.disable_baseline,
        ],
        canOpenPersonModal: [
            (s) => [s.filters, s.isInDashboardContext],
            (filters, isInDashboardContext): boolean => {
                return !isInDashboardContext && !filters.funnel_aggregate_by_hogql
            },
        ],
    }),

    listeners: ({ values }) => ({
        openPersonsModalForStep: ({ step, stepIndex, converted }) => {
            if (values.isInDashboardContext) {
                return
            }

            openPersonsModal({
                // openPersonsModalForStep is for the baseline - for breakdown series use openPersonsModalForSeries
                url: generateBaselineConversionUrl(converted ? step.converted_people_url : step.dropped_people_url),
                title: funnelTitle({
                    converted,
                    // Note - when in a legend the step.order is always 0 so we use stepIndex instead
                    step: typeof stepIndex === 'number' ? stepIndex + 1 : step.order + 1,
                    label: step.name,
                    seriesId: step.order,
                    order_type: values.filters.funnel_order_type,
                }),
            })
        },
        openPersonsModalForSeries: ({ step, series, converted }) => {
            if (values.isInDashboardContext) {
                return
            }
            // Version of openPersonsModalForStep that accurately handles breakdown series
            const breakdownValues = getBreakdownStepValues(series, series.order)
            openPersonsModal({
                url: converted ? series.converted_people_url : series.dropped_people_url,
                title: funnelTitle({
                    converted,
                    step: step.order + 1,
                    breakdown_value: breakdownValues.isEmpty ? undefined : breakdownValues.breakdown_value.join(', '),
                    label: step.name,
                    seriesId: step.order,
                    order_type: values.filters.funnel_order_type,
                }),
            })
        },
        openCorrelationPersonsModal: ({ correlation, success }) => {
            if (values.isInDashboardContext) {
                return
            }

            if (correlation.result_type === FunnelCorrelationResultsType.Properties) {
                const { breakdown, breakdown_value } = parseBreakdownValue(correlation.event.event)
                openPersonsModal({
                    url: success ? correlation.success_people_url : correlation.failure_people_url,
                    title: funnelTitle({
                        converted: success,
                        step: values.steps.length,
                        breakdown_value,
                        label: breakdown,
                    }),
                })
            } else {
                const { name } = parseEventAndProperty(correlation.event)

                openPersonsModal({
                    url: success ? correlation.success_people_url : correlation.failure_people_url,
                    title: funnelTitle({
                        converted: success,
                        step: values.steps.length,
                        label: name,
                    }),
                })
            }
        },
    }),
})
