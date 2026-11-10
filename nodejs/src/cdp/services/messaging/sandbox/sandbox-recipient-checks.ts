import { logger } from '~/common/utils/logger'

import { MessageOptOutRecord } from '../../../types'
import { RecipientsManagerService } from '../../managers/recipients-manager.service'
import { EmailSuppressionService } from '../email-suppression.service'
import { FrequencyCapCheck } from '../recipient-preferences.service'

export type SandboxRecipientCheckDependencies = {
    suppression: Pick<EmailSuppressionService, 'isSuppressed'>
    recipients: Pick<RecipientsManagerService, 'get' | 'getPreference' | 'getAllMarketingMessagingPreference'>
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

export function canonicalRecipient(address: string): string {
    return address.trim().toLowerCase()
}

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
    const identifier = canonicalRecipient(address)
    if (
        optOuts.some(
            (optOut) =>
                canonicalRecipient(optOut.identifier) === identifier && [categoryId, '$all'].includes(optOut.categoryId)
        )
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
