import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'

import { HogFunctionInputSchemaType } from '~/types'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'

export type HogFunctionInputIntegrationFieldProps = {
    schema: HogFunctionInputSchemaType
    value?: any
    onChange?: (value: any) => void
}

export function HogFunctionInputIntegrationField({
    schema,
    value,
    onChange,
}: HogFunctionInputIntegrationFieldProps): JSX.Element {
    const { configuration } = useValues(hogFunctionConfigurationLogic)
    const { integrationsLoading, integrations } = useValues(integrationsLogic)

    if (integrationsLoading) {
        return <LemonSkeleton className="h-10" />
    }

    const relatedSchemaIntegration = configuration.inputs_schema?.find((input) => input.key === schema.integration_key)

    if (!relatedSchemaIntegration) {
        return (
            <div className="text-danger">
                Bad configuration: integration key {schema.integration_key} not found in schema
            </div>
        )
    }

    const integrationId = configuration.inputs?.[relatedSchemaIntegration.key]?.value
    const integration = integrations?.find((integration) => integration.id === integrationId)

    if (!integration) {
        return (
            <div className="border border-dashed h-10 rounded p-2 text-muted-alt italic">
                Configure {relatedSchemaIntegration.label} to continue
            </div>
        )
    }
    if (schema.integration_field === 'slack_channel') {
        return (
            <SlackChannelPicker
                value={value}
                onChange={(x) => onChange?.(x?.split('|')[0])}
                integration={integration}
            />
        )
    }
    return (
        <div className="text-danger">
            <p>Unsupported integration type: {schema.integration}</p>
        </div>
    )
}
