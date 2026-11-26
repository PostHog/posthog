import { Heading, Text } from '@posthog/quill'

import { IntegrationSettingsCard } from './IntegrationSettingsCard'

export function QuillMarketingIntegrationAdvancedSettings({
    availableIntegrations,
}: {
    availableIntegrations: readonly string[]
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <Heading size="sm" render={<h3 className="m-0" />}>
                Integration-specific settings
            </Heading>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Configure campaign name mappings, custom UTM source mappings, and field preferences for each ad platform
                integration.
            </Text>
            <div className="flex flex-wrap gap-2">
                {availableIntegrations.map((integration) => (
                    <IntegrationSettingsCard key={integration} integrationName={integration} />
                ))}
            </div>
        </div>
    )
}
