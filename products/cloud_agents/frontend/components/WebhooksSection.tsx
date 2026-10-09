import { LemonBanner } from '@posthog/lemon-ui'

import { SettingsSection } from './SettingsSection'

export function WebhooksSection(): JSX.Element {
    return (
        <SettingsSection title="Webhooks" data-attr="cloud-agents-webhooks">
            <LemonBanner type="info" className="max-w-180">
                Webhooks for run events are not available yet. To follow a run, read it from the API or open it here.
            </LemonBanner>
        </SettingsSection>
    )
}
