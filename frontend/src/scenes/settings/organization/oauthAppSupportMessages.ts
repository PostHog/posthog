import { OrganizationOAuthApplicationApi } from '~/generated/core/api.schemas'

import { PROVISIONING_STATUS_LABELS } from './oauthAppProvisioningStatus'

export function reviewSupportMessage(app: OrganizationOAuthApplicationApi): string {
    return [
        'I have a question about the provisioning review of our OAuth application.',
        '',
        `Application: ${app.name}`,
        `Client ID: ${app.client_id}`,
        `Provisioning: ${PROVISIONING_STATUS_LABELS[app.provisioning_status]}`,
        '',
        'Our question:',
        '',
    ].join('\n')
}

export function verificationRequestMessage(app: OrganizationOAuthApplicationApi): string {
    return [
        'We would like PostHog to verify our OAuth application.',
        '',
        `Application: ${app.name}`,
        `Client ID: ${app.client_id}`,
        '',
        "Our product's website:",
        'What the application does with PostHog:',
        'A contact for security questions:',
        '',
    ].join('\n')
}
