import { EmailAttachmentMetadata } from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocation } from '~/cdp/types'

export function fileBytesOf(invocation: CyclotronJobInvocation): number | null {
    const sent = (invocation.state as { send?: { attachments?: readonly EmailAttachmentMetadata[] } } | null)?.send
    const queued = invocation.queueParameters?.type === 'email' ? invocation.queueParameters.attachments : undefined
    const files = sent?.attachments ?? queued
    return files?.length ? declaredFileBytes(files) : null
}

export const declaredFileBytes = (files: readonly EmailAttachmentMetadata[]): number =>
    files.reduce((total, file) => total + file.sizeBytes, 0)
