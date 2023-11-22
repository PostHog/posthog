import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { funnelTitle } from 'scenes/trends/persons-modal/persons-modal-utils'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import {
    FunnelCorrelation,
    FunnelCorrelationResultsType,
    FunnelStep,
    FunnelStepWithConversionMetrics,
    InsightLogicProps,
} from '~/types'

import { funnelDataLogic } from './funnelDataLogic'
import type { funnelPersonsModalLogicType } from './funnelPersonsModalLogicType'
import {
    generateBaselineConversionUrl,
    getBreakdownStepValues,
    parseBreakdownValue,
    parseEventAndProperty,
} from './funnelUtils'

const DEFAULT_FUNNEL_LOGIC_KEY = 'default_funnel_key'

export const funnelPersonsModalLogic = kea<funnelPersonsModalLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_FUNNEL_LOGIC_KEY)),
    path((key) => ['scenes', 'funnels', 'funnelPersonsModalLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [insightLogic(props), ['isInDashboardContext'], funnelDataLogic(props), ['steps', 'funnelsFilter']],
    })),

    actions({
        openPersonsModalForStep: ({
            step,
            stepIndex,
            converted,
        }: {
            step: FunnelStep
            stepIndex?: number
            converted: boolean
        }) => ({
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
        openCorrelationPersonsModal: (correlation: FunnelCorrelation, success: boolean) => ({
            correlation,
            success,
        }),
    }),

    selectors({
        canOpenPersonModal: [
            (s) => [s.funnelsFilter, s.isInDashboardContext],
            (funnelsFilter, isInDashboardContext): boolean => {
                return !isInDashboardContext && !funnelsFilter?.funnel_aggregate_by_hogql
            },
        ],
    }),

    listeners(({ values }) => ({
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
                    order_type: values.funnelsFilter?.funnel_order_type,
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
                    order_type: values.funnelsFilter?.funnel_order_type,
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
    })),
])
