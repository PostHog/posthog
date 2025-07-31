import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'

import { elementsToAction } from 'scenes/activity/explore/createActionFromEvent'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { funnelTitle } from 'scenes/trends/persons-modal/persons-modal-utils'

import {
    EventsNode,
    FunnelCorrelationActorsQuery,
    FunnelCorrelationQuery,
    FunnelsActorsQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    FunnelCorrelation,
    FunnelCorrelationResultsType,
    FunnelStep,
    FunnelStepWithConversionMetrics,
    InsightLogicProps,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { funnelDataLogic } from './funnelDataLogic'
import type { funnelPersonsModalLogicType } from './funnelPersonsModalLogicType'
import { getBreakdownStepValues, parseBreakdownValue, parseEventAndProperty } from './funnelUtils'

const DEFAULT_FUNNEL_LOGIC_KEY = 'default_funnel_key'

export const funnelPersonsModalLogic = kea<funnelPersonsModalLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_FUNNEL_LOGIC_KEY)),
    path((key) => ['scenes', 'funnels', 'funnelPersonsModalLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            insightLogic(props),
            ['isInDashboardContext', 'isInExperimentContext'],
            funnelDataLogic(props),
            ['steps', 'querySource', 'funnelsFilter'],
        ],
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
            (s) => [s.funnelsFilter],
            (funnelsFilter): boolean => {
                return !funnelsFilter?.funnelAggregateByHogQL
            },
        ],
    }),

    listeners(({ values }) => ({
        openPersonsModalForStep: ({ step, stepIndex, converted }) => {
            // Note - when in a legend the step.order is always 0 so we use stepIndex instead
            const stepNo = typeof stepIndex === 'number' ? stepIndex + 1 : step.order + 1
            const title = funnelTitle({
                converted,
                step: stepNo,
                label: step.name,
                seriesId: step.order,
                order_type: values.funnelsFilter?.funnelOrderType,
            })

            // openPersonsModalForStep is for the baseline - for breakdown series use openPersonsModalForSeries
            const query: FunnelsActorsQuery = {
                kind: NodeKind.FunnelsActorsQuery,
                source: values.querySource!,
                funnelStep: converted ? stepNo : -stepNo,
                includeRecordings: true,
            }
            openPersonsModal({ title, query, additionalSelect: { matched_recordings: 'matched_recordings' } })
        },
        openPersonsModalForSeries: ({ step, series, converted }) => {
            const stepNo = step.order + 1
            const breakdownValues = getBreakdownStepValues(series, series.order)
            const title = funnelTitle({
                converted,
                step: stepNo,
                breakdown_value: breakdownValues.isEmpty ? undefined : breakdownValues.breakdown_value.join(', '),
                label: step.name,
                seriesId: step.order,
                order_type: values.funnelsFilter?.funnelOrderType,
            })

            // Version of openPersonsModalForStep that accurately handles breakdown series
            const query: FunnelsActorsQuery = {
                kind: NodeKind.FunnelsActorsQuery,
                source: values.querySource!,
                funnelStep: converted ? stepNo : -stepNo,
                funnelStepBreakdown: series.breakdown_value === 'Baseline' ? null : series.breakdown_value,
                includeRecordings: true,
            }
            openPersonsModal({ title, query, additionalSelect: { matched_recordings: 'matched_recordings' } })
        },
        openCorrelationPersonsModal: ({ correlation, success }) => {
            if (correlation.result_type === FunnelCorrelationResultsType.Properties) {
                const { breakdown, breakdown_value } = parseBreakdownValue(correlation.event.event)
                const title = funnelTitle({
                    converted: success,
                    step: values.steps.length,
                    breakdown_value,
                    label: breakdown,
                })

                // properties
                const [propertyName, propertyValue] = correlation.event.event.split('::')
                const propType = values.querySource?.aggregation_group_type_index ? 'group' : 'person'
                const actorsQuery: FunnelsActorsQuery = {
                    kind: NodeKind.FunnelsActorsQuery,
                    source: values.querySource!,
                    funnelStep: 1,
                    includeRecordings: true,
                }
                const correlationQuery: FunnelCorrelationQuery = {
                    kind: NodeKind.FunnelCorrelationQuery,
                    source: actorsQuery,
                    funnelCorrelationType: correlation.result_type,
                }
                const query: FunnelCorrelationActorsQuery = {
                    kind: NodeKind.FunnelCorrelationActorsQuery,
                    source: correlationQuery,
                    funnelCorrelationPersonConverted: success,
                    funnelCorrelationPropertyValues: [
                        {
                            key: propertyName,
                            value: propertyValue,
                            type: propType === 'person' ? PropertyFilterType.Person : PropertyFilterType.Group,
                            operator: PropertyOperator.Exact,
                            group_type_index: values.querySource?.aggregation_group_type_index,
                        },
                    ],
                }
                openPersonsModal({
                    title,
                    query,
                    additionalSelect: { matched_recordings: 'matched_recordings' },
                })
            } else {
                const { name } = parseEventAndProperty(correlation.event)
                const title = funnelTitle({
                    converted: success,
                    step: values.steps.length,
                    label: name,
                })

                const actorsQuery: FunnelsActorsQuery = {
                    kind: NodeKind.FunnelsActorsQuery,
                    source: values.querySource!,
                    funnelStep: 1,
                    includeRecordings: true,
                }
                const correlationQuery: FunnelCorrelationQuery = {
                    kind: NodeKind.FunnelCorrelationQuery,
                    source: actorsQuery,
                    funnelCorrelationType: correlation.result_type,
                }

                let entity: EventsNode
                if (correlation.result_type === FunnelCorrelationResultsType.Events) {
                    // events
                    entity = {
                        event: correlation.event.event,
                        kind: NodeKind.EventsNode,
                    }
                } else {
                    // events with properties
                    const eventName = correlation.event.event.split('::')[0]

                    let properties: AnyPropertyFilter[]
                    if (eventName === '$autocapture') {
                        // If we have an $autocapture event, we need to
                        // convert the `elements` chain into an "action".
                        const elements = correlation.event.elements
                        const elementsAsAction = elementsToAction(elements)
                        properties = Object.entries(elementsAsAction)
                            .map(([propertyKey, propertyValue]) => {
                                if (propertyValue !== null) {
                                    return {
                                        key: propertyKey,
                                        value: [propertyValue],
                                        type: 'element',
                                        operator: 'exact',
                                    }
                                }
                            })
                            .filter(Boolean) as AnyPropertyFilter[]
                    } else {
                        const [_, propertyName, propertyValue] = correlation.event.event.split('::')

                        properties = [
                            {
                                key: propertyName,
                                value: propertyValue,
                                type: PropertyFilterType.Event,
                                operator: PropertyOperator.Exact,
                            },
                        ]
                    }

                    entity = {
                        kind: NodeKind.EventsNode,
                        event: eventName,
                        properties,
                    }
                }

                const query: FunnelCorrelationActorsQuery = {
                    kind: NodeKind.FunnelCorrelationActorsQuery,
                    source: correlationQuery,
                    funnelCorrelationPersonConverted: success,
                    funnelCorrelationPersonEntity: entity,
                }

                openPersonsModal({
                    title,
                    query,
                    additionalSelect: { matched_recordings: 'matched_recordings' },
                })
            }
        },
    })),
])
