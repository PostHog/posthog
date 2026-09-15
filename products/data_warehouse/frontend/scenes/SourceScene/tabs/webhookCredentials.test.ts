import { SourceConfig, SourceFieldConfig } from '~/queries/schema/schema-general'
import { WebhookInfo } from '~/types'

import { missingWebhookCredentials } from './webhookCredentials'

const signingSecret = {
    type: 'password',
    name: 'signing_secret',
    label: 'Signing secret',
    required: true,
    placeholder: '',
    secret: true,
} as SourceFieldConfig

const optionalField = { ...signingSecret, name: 'note', required: false } as SourceFieldConfig

const sourceConfig = { name: 'Mailgun', webhookFields: [signingSecret, optionalField] } as SourceConfig

const webhookInfo = (inputs: WebhookInfo['inputs']): WebhookInfo =>
    ({ supports_webhooks: true, exists: true, inputs }) as WebhookInfo

describe('missingWebhookCredentials', () => {
    it('reports a required credential that has no value', () => {
        expect(missingWebhookCredentials(webhookInfo({}), sourceConfig)).toEqual([signingSecret])
        expect(missingWebhookCredentials(webhookInfo({ signing_secret: { value: '' } }), sourceConfig)).toEqual([
            signingSecret,
        ])
    })

    it('treats the redacted secret marker as a value', () => {
        expect(missingWebhookCredentials(webhookInfo({ signing_secret: { secret: true } }), sourceConfig)).toEqual([])
    })

    it('reports nothing before the webhook exists', () => {
        expect(missingWebhookCredentials({ supports_webhooks: true, exists: false } as WebhookInfo, sourceConfig)).toEqual(
            []
        )
    })
})
