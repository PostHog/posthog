import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'

export const INSIGHT_ALERT_DESTINATION_LOGIC_KEY = 'insightAlertDestination'

export function AlertDestinationSelector(): JSX.Element {
    return (
        <LinkedHogFunctions
            logicKey={INSIGHT_ALERT_DESTINATION_LOGIC_KEY}
            type="internal_destination"
            subTemplateId="insight-alert-firing"
            filters={{}}
        />
    )
}
