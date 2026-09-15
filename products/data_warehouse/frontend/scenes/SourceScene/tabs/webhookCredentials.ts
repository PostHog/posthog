import { SourceConfig, SourceFieldConfig } from '~/queries/schema/schema-general'
import { WebhookInfo, WebhookInputValue } from '~/types'

const hasValue = (input: WebhookInputValue | undefined): boolean => {
    if (!input) {
        return false
    }
    // A set secret is redacted to `{ secret: true }`, so the marker is the only proof it has a value.
    if ('secret' in input) {
        return input.secret
    }
    return input.value !== undefined && input.value !== null && input.value !== ''
}

/**
 * Required webhook credentials the user has not given yet. While one is missing, the webhook
 * accepts every delivery and drops it. The provider stops retrying, but no data arrives.
 */
export function missingWebhookCredentials(
    webhookInfo: WebhookInfo | null,
    sourceConfig: SourceConfig | null
): SourceFieldConfig[] {
    if (!webhookInfo?.exists) {
        return []
    }

    const inputs = webhookInfo.inputs ?? {}

    return (sourceConfig?.webhookFields ?? []).filter(
        (field) => 'required' in field && field.required && !hasValue(inputs[field.name])
    )
}
