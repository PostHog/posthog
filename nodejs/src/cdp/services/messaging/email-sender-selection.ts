import { createHash } from 'crypto'

type EmailSenderConfiguration = {
    integrationId: number
    integrationIds?: number[]
}

export function selectEmailSenderIntegrationId(invocationId: string, sender: EmailSenderConfiguration): number {
    const configuredIds = sender.integrationIds?.length ? sender.integrationIds : [sender.integrationId]
    const integrationIds = [...new Set(configuredIds)].sort((a, b) => a - b)

    if (integrationIds.length === 1) {
        return integrationIds[0]
    }

    const hash = createHash('sha256')
        .update(`${invocationId}:${integrationIds.join(',')}`)
        .digest()
    return integrationIds[hash.readUInt32BE(0) % integrationIds.length]
}
