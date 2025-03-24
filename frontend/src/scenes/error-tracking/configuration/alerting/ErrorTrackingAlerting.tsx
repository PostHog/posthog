import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'

export function ErrorTrackingAlerting(): JSX.Element {
    return (
        <LinkedHogFunctions
            logicKey="error-tracking"
            type="internal_destination"
            subTemplateId="error-tracking"
            filters={{}}
        />
    )
}
