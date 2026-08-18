import sortBy from 'lodash.sortby'

import { dayjs } from 'lib/dayjs'

import { PUBLIC_EMAIL_DOMAINS, YC_BATCHES } from './constants'

export function getEmailDomain(email: string | null | undefined): string {
    if (!email) {
        return ''
    }

    const atIndex = email.lastIndexOf('@')
    return atIndex === -1 || atIndex === email.length - 1 ? '' : email.slice(atIndex + 1).toLowerCase()
}

export function isPublicEmailDomain(email: string | null | undefined): boolean {
    const domain = getEmailDomain(email)
    return !!domain && PUBLIC_EMAIL_DOMAINS.has(domain)
}

/**
 * Generates YC batch options for the dropdown, showing relevant batches based on current date.
 *
 * - Finds the current batch (most recent batch that has started)
 * - Returns current batch, all previous batches and 2 upcoming batches (newest first)
 * - Adds placeholder at the top and "Earlier batches" at the bottom
 */
export function getYCBatchOptions(): { label: string; value: string }[] {
    // Sort batches by start date (oldest first)
    const sortedBatches = sortBy(YC_BATCHES, (batch) => dayjs(batch.start_date))

    // Find current batch index (most recent batch where start date is today or in the past)
    const today = dayjs()
    const firstFutureBatchIndex = sortedBatches.findIndex((batch) => dayjs(batch.start_date).isAfter(today))
    // If no future batches exist, last batch is current batch
    const currentBatchIndex = firstFutureBatchIndex === -1 ? sortedBatches.length - 1 : firstFutureBatchIndex - 1

    // Take current batch, all previous batches and 2 upcoming batches
    const endIndex = Math.max(0, currentBatchIndex + 3)
    const relevantBatches = sortedBatches.slice(0, endIndex)

    const batchOptions = relevantBatches.reverse().map((batch) => ({
        label: batch.batch_name,
        value: batch.batch_name,
    }))

    return [{ label: 'Select your batch', value: '' }, ...batchOptions, { label: 'Earlier batches', value: 'Earlier' }]
}

const SHORT_CODE_SEASONS: Record<string, string> = {
    W: 'Winter',
    X: 'Spring',
    S: 'Summer',
    F: 'Fall',
}

/**
 * Converts a YC batch short code (as returned by YC's verification API) to its full name,
 * e.g. "S26" -> "Summer 2026". Returns null for anything else.
 */
export function convertShortCodeToFullBatchName(shortCode: string): string | null {
    const match = /^([WXSF])(\d{2})$/i.exec(shortCode.trim())
    if (!match) {
        return null
    }
    return `${SHORT_CODE_SEASONS[match[1].toUpperCase()]} 20${match[2]}`
}

/**
 * Picks the batch dropdown value to auto-fill from the batch short codes on a verified YC link.
 * Prefers a batch that exists in the dropdown options, falls back to "Earlier" for batches
 * older than the listed ones, and returns null if no code is recognizable.
 */
export function getBatchValueFromVerification(
    batchShortCodes: string[],
    batchOptions: { label: string; value: string }[]
): string | null {
    const fullNames = batchShortCodes
        .map(convertShortCodeToFullBatchName)
        .filter((name): name is string => name !== null)
    if (fullNames.length === 0) {
        return null
    }
    const optionValues = new Set(batchOptions.map((option) => option.value))
    return fullNames.find((name) => optionValues.has(name)) ?? 'Earlier'
}
