import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'

export function ErrorTrackingAlerting(): JSX.Element {
    return (
        <LinkedHogFunctions
            logicKey="error-tracking"
            type="destination"
            subTemplateId="error-tracking-issue-created"
            filters={{}}
        />
    )
}
