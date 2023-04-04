import { BreakPointFunction, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { EntityTypes, FunnelCorrelationResultsType, InsightLogicProps } from '~/types'
import { visibilitySensorLogic } from 'lib/components/VisibilitySensor/visibilitySensorLogic'

import type { funnelCorrelationUsageLogicType } from './funnelCorrelationUsageLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { parseEventAndProperty } from './funnelUtils'

export const funnelCorrelationUsageLogic = kea<funnelCorrelationUsageLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('insight_funnel')),
    path((key) => ['scenes', 'funnels', 'funnelCorrelationFeedbackLogic', key]),

    connect((props: InsightLogicProps) => ({
        logic: [eventUsageLogic],

        actions: [
            insightLogic(props),
            ['loadResultsSuccess'],
            insightDataLogic(props),
            ['loadDataSuccess'],
            eventUsageLogic,
            ['reportCorrelationViewed', 'reportCorrelationInteraction'],
        ],
    })),

    reducers({
        shouldReportCorrelationViewed: [
            true as boolean,
            {
                loadResultsSuccess: () => true,
                loadDataSuccess: () => true,
                // [eventUsageLogic.actionTypes.reportCorrelationViewed]: (current, { propertiesTable }) => {
                //     if (!propertiesTable) {
                //         return false
                //     }
                //     return current
                // },
            },
        ],
        shouldReportPropertyCorrelationViewed: [
            true as boolean,
            {
                loadResultsSuccess: () => true,
                loadDataSuccess: () => true,
                // [eventUsageLogic.actionTypes.reportCorrelationViewed]: (current, { propertiesTable }) => {
                //     if (propertiesTable) {
                //         return false
                //     }
                //     return current
                // },
            },
        ],
    }),

    selectors({
        correlationPropKey: [
            () => [(_, props) => props],
            (props): string => `correlation-${keyForInsightLogicProps('insight_funnel')(props)}`,
        ],
    }),

    listeners(({ values }) => ({
        // skew warning
        hideSkewWarning: () => {
            eventUsageLogic.actions.reportCorrelationInteraction(
                FunnelCorrelationResultsType.Events,
                'hide skew warning'
            )
        },

        // event correlation
        [visibilitySensorLogic({ id: values.correlationPropKey }).actionTypes.setVisible]: async (
            {
                visible,
            }: {
                visible: boolean
            },
            breakpoint: BreakPointFunction
        ) => {
            if (visible && values.shouldReportCorrelationViewed) {
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 0)
                await breakpoint(10000)
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 10)
            }
        },
        setCorrelationTypes: ({ types }) => {
            eventUsageLogic.actions.reportCorrelationInteraction(
                FunnelCorrelationResultsType.Events,
                'set correlation types',
                { types }
            )
        },
        excludeEventFromProject: async ({ eventName }) => {
            eventUsageLogic.actions.reportCorrelationInteraction(FunnelCorrelationResultsType.Events, 'exclude event', {
                event_name: eventName,
            })
        },

        // property correlation
        [visibilitySensorLogic({ id: `${values.correlationPropKey}-properties` }).actionTypes.setVisible]: async (
            {
                visible,
            }: {
                visible: boolean
            },
            breakpoint: BreakPointFunction
        ) => {
            if (visible && values.shouldReportPropertyCorrelationViewed) {
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 0, true)
                await breakpoint(10000)
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 10, true)
            }
        },
        setPropertyCorrelationTypes: ({ types }) => {
            eventUsageLogic.actions.reportCorrelationInteraction(
                FunnelCorrelationResultsType.Properties,
                'set property correlation types',
                { types }
            )
        },
        excludePropertyFromProject: ({ propertyName }) => {
            eventUsageLogic.actions.reportCorrelationInteraction(
                FunnelCorrelationResultsType.Events,
                'exclude person property',
                {
                    person_property: propertyName,
                }
            )
        },

        // event property correlation
        excludeEventPropertyFromProject: async ({ propertyName }) => {
            eventUsageLogic.actions.reportCorrelationInteraction(
                FunnelCorrelationResultsType.EventWithProperties,
                'exclude event property',
                {
                    property_name: propertyName,
                }
            )
        },
        loadEventWithPropertyCorrelations: async (eventName: string) => {
            eventUsageLogic.actions.reportCorrelationInteraction(
                FunnelCorrelationResultsType.EventWithProperties,
                'load event with properties',
                { name: eventName }
            )
        },

        // setPropertyNames: async ({ propertyNames }) => {
        //     eventUsageLogic.actions.reportCorrelationInteraction(
        //         FunnelCorrelationResultsType.Properties,
        //         'set property names',
        //         { property_names: propertyNames.length === values.allProperties.length ? '$all' : propertyNames }
        //     )
        // },

        // person modal
        openCorrelationPersonsModal: ({ correlation, success }) => {
            if (values.isInDashboardContext) {
                return
            }

            if (correlation.result_type === FunnelCorrelationResultsType.Properties) {
                eventUsageLogic.actions.reportCorrelationInteraction(
                    FunnelCorrelationResultsType.Properties,
                    'person modal',
                    values.filters.funnel_correlation_person_entity
                )
            } else {
                const { name, properties } = parseEventAndProperty(correlation.event)
                eventUsageLogic.actions.reportCorrelationInteraction(correlation.result_type, 'person modal', {
                    id: name,
                    type: EntityTypes.EVENTS,
                    properties,
                    converted: success,
                })
            }
        },
    })),
])
