import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'

import { PropertyFilterType, PropertyOperator } from '~/types'

export interface AlertDestinationSelectorProps {
    alertId?: string
}

export const INSIGHT_ALERT_DESTINATION_LOGIC_KEY = 'insightAlertDestination'
export const INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID = 'insight-alert-firing'

export function AlertDestinationSelector({ alertId }: AlertDestinationSelectorProps): JSX.Element {
    return (
        <LinkedHogFunctions
            logicKey={INSIGHT_ALERT_DESTINATION_LOGIC_KEY}
            type="destination"
            subTemplateId={INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID}
            filters={{
                events: [
                    {
                        id: '$insight_alert_firing',
                        type: 'events',
                        properties: [
                            {
                                key: 'alert_id',
                                value: alertId,
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ],
                    },
                ],
            }}
        />
    )
}
