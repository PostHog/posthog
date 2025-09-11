import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'

export function SidePanelActivitySubscriptions(): JSX.Element {
    return (
        <div className="deprecated-space-y-4">
            <p>Get notified of your team's activity</p>

            <LinkedHogFunctions type="internal_destination" subTemplateIds={['activity-log']} />
        </div>
    )
}
