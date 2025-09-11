import { INSIGHT_ALERT_FIRING_EVENT_ID, INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID } from 'lib/constants'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'

import { PropertyFilterType, PropertyOperator } from '~/types'

export interface AlertDestinationSelectorProps {
    alertId: string
}

export function AlertDestinationSelector({ alertId }: AlertDestinationSelectorProps): JSX.Element {
    return (
        <LinkedHogFunctions
            type="internal_destination"
            subTemplateIds={[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID]}
            hideFeedback={true}
            forceFilterGroups={[
                {
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
                },
            ]}
        />
    )
}
