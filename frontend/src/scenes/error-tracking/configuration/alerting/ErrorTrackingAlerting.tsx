import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'

import { AvailableFeature } from '~/types'

export function ErrorTrackingAlerting(): JSX.Element {
    return (
        <LinkedHogFunctions
            logicKey="error-tracking"
            type="internal_destination"
            subTemplateId="error-tracking"
            filters={{}}
            feature={AvailableFeature.ERROR_TRACKING_DESTINATIONS}
        />
    )
}
