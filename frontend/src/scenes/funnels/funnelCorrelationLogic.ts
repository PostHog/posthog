import { kea, props, key, path, selectors, listeners, connect, BreakPointFunction, reducers } from 'kea'
import { InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { visibilitySensorLogic } from 'lib/components/VisibilitySensor/visibilitySensorLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { funnelLogic } from './funnelLogic'

import type { funnelCorrelationLogicType } from './funnelCorrelationLogicType'

export const funnelCorrelationLogic = kea<funnelCorrelationLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('insight_funnel')),
    path((key) => ['scenes', 'funnels', 'funnelCorrelationLogic', key]),
    connect({
        values: [funnelLogic, ['filters']],
        actions: [funnelLogic, ['loadResultsSuccess']],
        logic: [eventUsageLogic],
    }),
    selectors({
        correlationPropKey: [
            () => [(_, props) => props],
            (props): string => `correlation-${keyForInsightLogicProps('insight_funnel')(props)}`,
        ],
    }),
    reducers({
        shouldReportCorrelationViewed: [
            true as boolean,
            {
                loadResultsSuccess: () => true,
                [eventUsageLogic.actionTypes.reportCorrelationViewed]: (current, { propertiesTable }) => {
                    if (!propertiesTable) {
                        return false // don't report correlation viewed again, since it was for events earlier
                    }
                    return current
                },
            },
        ],
        shouldReportPropertyCorrelationViewed: [
            true as boolean,
            {
                loadResultsSuccess: () => true,
                [eventUsageLogic.actionTypes.reportCorrelationViewed]: (current, { propertiesTable }) => {
                    if (propertiesTable) {
                        return false
                    }
                    return current
                },
            },
        ],
    }),
    listeners(({ values }) => ({
        [visibilitySensorLogic({ id: values.correlationPropKey }).actionTypes.setVisible]: async (
            { visible }: { visible: boolean },
            breakpoint: BreakPointFunction
        ) => {
            if (visible && values.shouldReportCorrelationViewed) {
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 0)
                await breakpoint(10000)
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 10)
            }
        },

        [visibilitySensorLogic({ id: `${values.correlationPropKey}-properties` }).actionTypes.setVisible]: async (
            { visible }: { visible: boolean },
            breakpoint: BreakPointFunction
        ) => {
            if (visible && values.shouldReportPropertyCorrelationViewed) {
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 0, true)
                await breakpoint(10000)
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 10, true)
            }
        },
    })),
])
