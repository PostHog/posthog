import { IntegrationType } from '~/types'

import { EmailTemplateFrom } from './types'

// Mirrors how the send path picks a sender: the rotation list when one is set, otherwise the single sender.
export function getUnverifiedEmailSenders(
    from: EmailTemplateFrom | undefined,
    integrations: IntegrationType[] | null
): IntegrationType[] {
    const sendingIds = new Set(from?.integrationIds?.length ? from.integrationIds : [from?.integrationId])
    return (integrations ?? []).filter(
        (integration) =>
            integration.kind === 'email' && sendingIds.has(integration.id) && integration.config?.verified !== true
    )
}

export function getEmailSenderAddress(integration: IntegrationType): string {
    return integration.config?.email ?? integration.display_name
}
