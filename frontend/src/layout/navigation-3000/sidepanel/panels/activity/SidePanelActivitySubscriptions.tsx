import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'

export function SidePanelActivitySubscriptions(): JSX.Element {
    return (
        <div className="space-y-4 ">
            <p>Get notified of your team's activity</p>

            <LinkedHogFunctions
                type="internal_destination"
                subTemplateId="activity_log"
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
