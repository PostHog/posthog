import { PostgresRouter } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

import { MessageOptOutRecord } from '../../../types'
import { RecipientsManagerService } from '../../managers/recipients-manager.service'
import { EmailSuppressionConfig, EmailSuppressionService } from '../email-suppression.service'
import { FrequencyCapCheck } from '../recipient-preferences.service'
import { readerBeforeDeadline } from './sandbox-authorization'

export const RECIPIENT_READ_TIMEOUT_MS = 2_000

export type SandboxRecipientCheckDependencies = {
    suppression: Pick<EmailSuppressionService, 'isSuppressed'>
    recipients: Pick<RecipientsManagerService, 'get' | 'getPreference' | 'getAllMarketingMessagingPreference'>
}

export function sandboxRecipientReads(
    db: PostgresRouter,
    suppressionConfig: EmailSuppressionConfig,
    timeoutMs: number = RECIPIENT_READ_TIMEOUT_MS
): SandboxRecipientCheckDependencies {
    const reader = readerBeforeDeadline(db, timeoutMs, 'sandbox-email-recipient')
    return {
        suppression: new EmailSuppressionService(reader, suppressionConfig),
        recipients: new RecipientsManagerService(reader),
    }
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
    { suppression, recipients }: SandboxRecipientCheckDependencies,
    { teamId, address, categoryId, categoryType, optOuts, isTest, frequencyCap }: SandboxRecipientCheckRequest
): Promise<SandboxRecipientCheck> {
    const transactional = categoryType === 'transactional'
    try {
        if (await suppression.isSuppressed(teamId, address, { transactional })) {
            return { ok: false, reason: 'suppressed' }
        }
        if (transactional) {
            return { ok: true }
        }
        if (await isOptedOut(recipients, { teamId, address, categoryId: categoryId || '$all', optOuts })) {
            return { ok: false, reason: 'opted_out' }
        }
    } catch (error) {
        logger.warn('Could not read sandbox recipient suppression or preferences', { teamId, error: String(error) })
        return { ok: false, reason: 'authorization_unavailable' }
    }
    if (!isTest && (await frequencyCap()).capped) {
        return { ok: false, reason: 'frequency_capped' }
    }
    return { ok: true }
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
