import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'

import { PropertyFilterType, PropertyOperator } from '~/types'

export interface AlertDestinationSelectorProps {
    alertId: string
}

export const INSIGHT_ALERT_DESTINATION_LOGIC_KEY = 'insightAlertDestination'
export const INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID = 'insight-alert-firing'
export const INSIGHT_ALERT_FIRING_EVENT_ID = '$insight_alert_firing'

export function AlertDestinationSelector({ alertId }: AlertDestinationSelectorProps): JSX.Element {
    return (
        <LinkedHogFunctions
            logicKey={INSIGHT_ALERT_DESTINATION_LOGIC_KEY}
            type="internal_destination"
            subTemplateIds={[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID]}
            hideFeedback={true}
            filters={{
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
            }}
        />
    )
}
