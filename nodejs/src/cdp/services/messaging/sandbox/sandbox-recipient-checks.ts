import { logger } from '~/common/utils/logger'

import { MessageOptOutRecord } from '../../../types'
import { RecipientsManagerService } from '../../managers/recipients-manager.service'
import { EmailSuppressionService } from '../email-suppression.service'
import { FrequencyCapCheck } from '../recipient-preferences.service'

export const RECIPIENT_READ_TIMEOUT_MS = 2_000

export type SandboxRecipientCheckDependencies = {
    suppression: Pick<EmailSuppressionService, 'isSuppressed'>
    recipients: Pick<RecipientsManagerService, 'get' | 'getPreference' | 'getAllMarketingMessagingPreference'>
    timeoutMs?: number
}

export type SandboxRecipientCheckRequest = {
    teamId: number
    address: string
    categoryId?: string
    categoryType?: 'marketing' | 'transactional'
    optOuts: MessageOptOutRecord[]
    isTest: boolean
    frequencyCap: () => Promise<FrequencyCapCheck>
}

export type SandboxRecipientCheck =
    | { ok: true }
    | { ok: false; reason: 'suppressed' | 'opted_out' | 'frequency_capped' | 'authorization_unavailable' }

export async function checkSandboxRecipient(
    { suppression, recipients, timeoutMs = RECIPIENT_READ_TIMEOUT_MS }: SandboxRecipientCheckDependencies,
    { teamId, address, categoryId, categoryType, optOuts, isTest, frequencyCap }: SandboxRecipientCheckRequest
): Promise<SandboxRecipientCheck> {
    const transactional = categoryType === 'transactional'
    let blocked: 'suppressed' | 'opted_out' | null
    try {
        blocked = await beforeDeadline(
            (async () => {
                if (await suppression.isSuppressed(teamId, address, { transactional })) {
                    return 'suppressed'
                }
                if (transactional) {
                    return null
                }
                const optedOut = await isOptedOut(recipients, {
                    teamId,
                    address,
                    categoryId: categoryId || '$all',
                    optOuts,
                })
                return optedOut ? 'opted_out' : null
            })(),
            timeoutMs
        )
    } catch (error) {
        logger.warn('Could not read sandbox recipient suppression or preferences', { teamId, error: String(error) })
        return { ok: false, reason: 'authorization_unavailable' }
    }
    if (blocked) {
        return { ok: false, reason: blocked }
    }
    if (transactional) {
        return { ok: true }
    }
    if (!isTest && (await frequencyCap()).capped) {
        return { ok: false, reason: 'frequency_capped' }
    }
    return { ok: true }
}

async function beforeDeadline<T>(work: Promise<T>, timeoutMs: number): Promise<T> {
    let timer: NodeJS.Timeout | undefined
    const deadline = new Promise<never>((_, reject) => {
        timer = setTimeout(
            () => reject(new Error(`The sandbox recipient read passed its ${timeoutMs} ms deadline`)),
            timeoutMs
        )
    })
    try {
        return await Promise.race([work, deadline])
    } finally {
        clearTimeout(timer)
    }
}

async function isOptedOut(
    recipients: SandboxRecipientCheckDependencies['recipients'],
    {
        teamId,
        address,
        categoryId,
        optOuts,
    }: { teamId: number; address: string; categoryId: string; optOuts: MessageOptOutRecord[] }
): Promise<boolean> {
    const identifier = address.trim()
    if (
        optOuts.some((optOut) => optOut.identifier === identifier && [categoryId, '$all'].includes(optOut.categoryId))
    ) {
        return true
    }
    const recipient = await recipients.get({ teamId, identifier: address })
    return (
        !!recipient &&
        (recipients.getPreference(recipient, categoryId) === 'OPTED_OUT' ||
            recipients.getAllMarketingMessagingPreference(recipient) === 'OPTED_OUT')
    )
}
