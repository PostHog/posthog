import { INSIGHT_ALERT_FIRING_EVENT_ID } from 'lib/constants'

import { CyclotronJobFiltersType, PropertyFilterType, PropertyOperator } from '~/types'

export const buildAlertFilterConfig = (alertId: string): CyclotronJobFiltersType => ({
    properties: [
        {
            key: 'alert_id',
            value: alertId,
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        },
    ],
    events: [
        {
            id: INSIGHT_ALERT_FIRING_EVENT_ID,
            type: 'events',
        },
    ],
})
