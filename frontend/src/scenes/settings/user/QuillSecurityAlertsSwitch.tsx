import { SECURITY_ALERTS_DESCRIPTION } from './emailPreferencesCopy'
import { QuillNotificationSwitch } from './QuillNotificationSwitch'

export function QuillSecurityAlertsSwitch(): JSX.Element {
    return (
        <QuillNotificationSwitch
            dataAttr="security_alerts_enabled"
            checked={true}
            disabledReason="These notifications cannot be disabled."
            label="Security alerts"
            description={SECURITY_ALERTS_DESCRIPTION}
        />
    )
}
