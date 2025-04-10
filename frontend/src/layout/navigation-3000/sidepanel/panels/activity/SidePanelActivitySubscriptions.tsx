import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'

export function SidePanelActivitySubscriptions(): JSX.Element {
    return (
        <div className="deprecated-space-y-4 ">
            <p>Get notified of your team's activity</p>

            <LinkedHogFunctions
                logicKey="activity-log"
                type="internal_destination"
                subTemplateId="activity-log"
                filters={{
                    events: [
                        {
                            id: `$activity_log_entry_created`,
                            type: 'events',
                        },
                    ],
                }}
            />
        </div>
    )
}
