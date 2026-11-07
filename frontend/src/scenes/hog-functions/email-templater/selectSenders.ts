import { SANDBOX_EMAIL_SENDER_NOTE } from 'lib/integrations/sandboxEmailSender'

import { IntegrationType } from '~/types'

import { EmailTemplateFrom, MAX_WORKFLOW_EMAIL_SENDERS } from './types'

export interface SenderOption {
    key: string
    label: string
    value: number
    /** Set only for the sandbox sender, so the menu can tag it. */
    labelComponent?: JSX.Element
}

export function selectedSenderIds(value: EmailTemplateFrom | undefined): number[] {
    if (value?.integrationIds?.length) {
        return value.integrationIds
    }
    return value?.integrationId ? [value.integrationId] : []
}

function exclusiveSandboxSenders(
    integrationIds: number[],
    sandboxSenderId: number | undefined,
    sandboxSelected: boolean
): number[] {
    if (sandboxSenderId === undefined || !integrationIds.includes(sandboxSenderId)) {
        return integrationIds
    }
    return sandboxSelected ? integrationIds.filter((id) => id !== sandboxSenderId) : [sandboxSenderId]
}

export function selectSenders(
    value: EmailTemplateFrom | undefined,
    integrationIds: number[],
    sandboxSenderId: number | undefined
): EmailTemplateFrom | null {
    const sandboxSelected = sandboxSenderId !== undefined && selectedSenderIds(value).includes(sandboxSenderId)
    const senders = exclusiveSandboxSenders(integrationIds, sandboxSenderId, sandboxSelected)
    if (senders.length > MAX_WORKFLOW_EMAIL_SENDERS) {
        return null
    }
    const sandboxChosen = sandboxSenderId !== undefined && senders.includes(sandboxSenderId)
    return {
        ...value,
        integrationId: senders[0],
        integrationIds: senders.length > 1 ? senders : undefined,
        ...(sandboxChosen ? { email: undefined, name: undefined } : {}),
    }
}

/** The senders the picker offers, with the sandbox sender last, or null until the integrations load. */
export function senderOptions(
    integrations: IntegrationType[] | null,
    ownEmailIntegrations: IntegrationType[],
    sandboxSender: IntegrationType | null,
    sandboxSenderLabel: (integration: IntegrationType) => JSX.Element
): SenderOption[] | null {
    if (!integrations) {
        return null
    }
    const senders = sandboxSender ? [...ownEmailIntegrations, sandboxSender] : ownEmailIntegrations
    return senders.map((integration) => ({
        key: String(integration.id),
        label: integration.display_name,
        value: integration.id,
        ...(integration.id === sandboxSender?.id ? { labelComponent: sandboxSenderLabel(integration) } : {}),
    }))
}

export function senderHintFor(sandboxSenderSelected: boolean, senderRotationEnabled: boolean): string | null {
    if (sandboxSenderSelected) {
        return SANDBOX_EMAIL_SENDER_NOTE
    }
    return senderRotationEnabled
        ? `Choose up to ${MAX_WORKFLOW_EMAIL_SENDERS} senders. Each workflow run uses one sender from this list.`
        : null
}
