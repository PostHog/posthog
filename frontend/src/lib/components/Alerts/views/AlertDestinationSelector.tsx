import { INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID } from 'lib/constants'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'

export interface AlertDestinationSelectorProps {
    alertId: string
}

export function AlertDestinationSelector({ alertId }: AlertDestinationSelectorProps): JSX.Element {
    return (
        <LinkedHogFunctions
            type="internal_destination"
            subTemplateIds={[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID]}
            hideFeedback={true}
            alertId={alertId}
        />
    )
}
