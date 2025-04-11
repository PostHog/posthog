import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import {
    GoogleAdsConversionActionPicker,
    GoogleAdsCustomerIdPicker,
} from 'lib/integrations/GoogleAdsIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LinearTeamPicker } from 'lib/integrations/LinearIntegrationHelpers'
import {
    LinkedInAdsAccountIdPicker,
    LinkedInAdsConversionRulePicker,
} from 'lib/integrations/LinkedInIntegrationHelpers'
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
    let requiresFieldValue: string | undefined

    if (schema.requires_field) {
        const requiresFieldSchema = configuration.inputs_schema?.find((input) => input.key === schema.requires_field)

        if (!requiresFieldSchema) {
            return (
                <div className="text-danger">
                    Bad configuration: required key {schema.requires_field} not found in schema
                </div>
            )
        }

        const requiresField = configuration.inputs?.[requiresFieldSchema.key]
        requiresFieldValue = requiresField?.value
        if (!requiresFieldValue) {
            return (
                <div className="border border-dashed h-10 rounded p-2 text-secondary italic">
                    Configure {requiresFieldSchema.label} to continue
                </div>
            )
        }
    }
    if (!integration) {
        return (
            <div className="border border-dashed h-10 rounded p-2 text-secondary italic">
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
    if (schema.integration_field === 'google_ads_conversion_action' && requiresFieldValue) {
        return (
            <GoogleAdsConversionActionPicker
                value={value}
                requiresFieldValue={requiresFieldValue}
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
    if (schema.integration_field === 'linkedin_ads_conversion_rule_id' && requiresFieldValue) {
        return (
            <LinkedInAdsConversionRulePicker
                value={value}
                requiresFieldValue={requiresFieldValue}
                onChange={(x) => onChange?.(x?.split('|')[0])}
                integration={integration}
            />
        )
    }
    if (schema.integration_field === 'linkedin_ads_account_id') {
        return (
            <LinkedInAdsAccountIdPicker
                value={value}
                onChange={(x) => onChange?.(x?.split('|')[0])}
                integration={integration}
            />
        )
    }
    if (schema.integration_field === 'linear_team') {
        return <LinearTeamPicker value={value} onChange={(x) => onChange?.(x)} integration={integration} />
    }
    return (
        <div className="text-danger">
            <p>Unsupported integration type: {schema.integration}</p>
        </div>
    )
}
