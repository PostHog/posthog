import { EmailTemplateFrom, MAX_WORKFLOW_EMAIL_SENDERS } from './types'

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
