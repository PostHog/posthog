import posthog from 'posthog-js'

import { TeamSettingToggle } from '../components/TeamSettingToggle'

export function DeadClicksAutocaptureSettings(): JSX.Element {
    return (
        <TeamSettingToggle
            field="capture_dead_clicks"
            label="Enable dead clicks autocapture"
            onChange={(checked) => posthog.capture('dead_clicks_autocapture_toggled', { isEnabled: checked })}
        />
    )
}
