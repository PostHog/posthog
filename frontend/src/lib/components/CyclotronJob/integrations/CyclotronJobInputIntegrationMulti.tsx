import { useValues } from 'kea'

import { LemonBanner, LemonInputSelect } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { getIntegrationNameFromKind } from 'lib/integrations/utils'

import { CyclotronJobInputSchemaType } from '~/types'

// Multi-select over the team's integration connections of one or more kinds. `schema.integration`
// carries a comma-separated list of kinds (e.g. "firebase,apns"); only connections that actually
// exist are offered, so platforms the team hasn't configured never show up as empty pickers.
export function CyclotronJobInputIntegrationMulti({
    schema,
    value,
    onChange,
}: {
    schema: CyclotronJobInputSchemaType
    value?: number[]
    onChange?: (value: number[]) => void
}): JSX.Element {
    const { integrations, integrationsLoading } = useValues(integrationsLogic)

    const kinds = (schema.integration ?? '')
        .split(',')
        .map((k) => k.trim())
        .filter(Boolean)
    const available = (integrations ?? []).filter((integration) => kinds.includes(integration.kind))

    if (!integrationsLoading && available.length === 0) {
        return (
            <LemonBanner type="warning" className="p-2">
                No {kinds.map(getIntegrationNameFromKind).join(' or ')} channels are configured. Add one from the
                Channels tab to send this notification.
            </LemonBanner>
        )
    }

    return (
        <LemonInputSelect
            mode="multiple"
            placeholder="Select one or more channels"
            loading={integrationsLoading}
            value={(value ?? []).map(String)}
            onChange={(values) => onChange?.(values.map(Number))}
            options={available.map((integration) => ({
                key: String(integration.id),
                label: `${integration.display_name || integration.kind} (${getIntegrationNameFromKind(integration.kind)})`,
            }))}
        />
    )
}
