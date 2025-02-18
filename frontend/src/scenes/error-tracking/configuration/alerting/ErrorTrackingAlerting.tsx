import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'

export function ErrorTrackingAlerting(): JSX.Element {
    return (
        <LinkedHogFunctions
            // logicKey="error-tracking-alerts"
            type="internal_destination"
            subTemplateId="error-tracking"
            filters={{
                events: [
                    {
                        id: `$error_tracking_issue_created`,
                        type: 'events',
                    },
                ],
            }}
        />
    )
}
