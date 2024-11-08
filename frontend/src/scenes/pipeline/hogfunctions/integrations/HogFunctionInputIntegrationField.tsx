import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import {
    GoogleAdsConversionActionPicker,
    GoogleAdsCustomerIdPicker,
} from 'lib/integrations/GoogleAdsIntegrationHelpers'
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
    let requiredFieldValue: string | undefined

    if (schema.required_field) {
        const requiredFieldSchema = configuration.inputs_schema?.find((input) => input.key === schema.required_field)

        if (!requiredFieldSchema) {
            return (
                <div className="text-danger">
                    Bad configuration: required key {schema.required_field} not found in schema
                </div>
            )
        }

        const requiredField = configuration.inputs?.[requiredFieldSchema.key]
        requiredFieldValue = requiredField?.value
        if (!requiredFieldValue) {
            return (
                <div className="border border-dashed h-10 rounded p-2 text-muted-alt italic">
                    Configure {requiredFieldSchema.label} to continue
                </div>
            )
        }
    }
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
    if (schema.integration_field === 'google_ads_conversion_action' && requiredFieldValue) {
        return (
            <GoogleAdsConversionActionPicker
                value={value}
                requiredFieldValue={requiredFieldValue}
                onChange={(x) => onChange?.(x?.split('|')[0])}
                integration={integration}
            />
        )
    }
    if (schema.integration_field === 'google_ads_customer_id') {
        return (
            <GoogleAdsCustomerIdPicker
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
