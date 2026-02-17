import { TeamSettingToggle } from '../components/TeamSettingToggle'

export function IPCapture(): JSX.Element {
    return <TeamSettingToggle field="anonymize_ips" label="Discard client IP data" />
}
