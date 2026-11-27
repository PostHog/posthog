import { Heading, Text } from '@posthog/quill'

import { CampaignFieldPreferencesConfiguration } from '../settings/CampaignFieldPreferencesConfiguration'
import { CampaignNameMappingsConfiguration } from '../settings/CampaignNameMappingsConfiguration'
import { CustomSourceMappingsConfiguration } from '../settings/CustomSourceMappingsConfiguration'

export function QuillUtmAuditSettingsTab({ integrationFilter }: { integrationFilter?: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-8">
            <section className="flex flex-col gap-2">
                <Heading size="sm" render={<h4 className="m-0" />}>
                    Match field
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Choose whether utm_campaign is matched against campaign names or campaign IDs for each integration.
                </Text>
                <CampaignFieldPreferencesConfiguration sourceFilter={integrationFilter} />
            </section>

            <section className="flex flex-col gap-2">
                <Heading size="sm" render={<h4 className="m-0" />}>
                    Custom source mappings
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Map custom utm_source values to an integration when they differ from the defaults.
                </Text>
                <CustomSourceMappingsConfiguration sourceFilter={integrationFilter} />
            </section>

            <section className="flex flex-col gap-2">
                <Heading size="sm" render={<h4 className="m-0" />}>
                    Campaign name mappings
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Manually map utm_campaign values to campaigns when names don't match automatically.
                </Text>
                <CampaignNameMappingsConfiguration sourceFilter={integrationFilter} />
            </section>
        </div>
    )
}
