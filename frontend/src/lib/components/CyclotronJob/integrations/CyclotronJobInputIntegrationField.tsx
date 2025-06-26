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

import { CyclotronJobInputSchemaType } from '~/types'

import { CyclotronJobInputConfiguration } from '../types'

export type CyclotronJobInputIntegrationFieldProps = {
    schema: CyclotronJobInputSchemaType
    value?: any
    onChange?: (value: any) => void
    configuration: CyclotronJobInputConfiguration
    parentConfiguration?: CyclotronJobInputConfiguration
}

export function CyclotronJobInputIntegrationField({
    schema,
    value,
    onChange,
    configuration,
    parentConfiguration,
}: CyclotronJobInputIntegrationFieldProps): JSX.Element {
    const combinedInputs = {
        ...configuration?.inputs,
        ...parentConfiguration?.inputs,
    }

    const combinedInputsSchema = [
        ...(configuration?.inputs_schema ?? []),
        ...(parentConfiguration?.inputs_schema ?? []),
    ]

    const { integrationsLoading, integrations } = useValues(integrationsLogic)

    if (integrationsLoading) {
        return <LemonSkeleton className="h-10" />
    }

    const relatedSchemaIntegration = combinedInputsSchema.find((input) => input.key === schema.integration_key)

    if (!relatedSchemaIntegration) {
        return (
            <div className="text-danger">
                Bad configuration: integration key {schema.integration_key} not found in schema
            </div>
        )
    }

    const integrationId = combinedInputs[relatedSchemaIntegration.key]?.value
    const integration = integrations?.find((integration) => integration.id === integrationId)
    let requiresFieldValue: string | undefined

    if (schema.requires_field) {
        const requiresFieldSchema = combinedInputsSchema.find((input) => input.key === schema.requires_field)

        if (!requiresFieldSchema) {
            return (
                <div className="text-danger">
                    Bad configuration: required key {schema.requires_field} not found in schema
                </div>
            )
        }

        const requiresField = combinedInputs?.[requiresFieldSchema.key]
        requiresFieldValue = requiresField?.value
        if (!requiresFieldValue) {
            return (
                <div className="p-2 h-10 italic rounded border border-dashed text-secondary">
                    Configure {requiresFieldSchema.label} to continue
                </div>
            )
        }
    }
    if (!integration) {
        return (
            <div className="p-2 h-10 italic rounded border border-dashed text-secondary">
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
