import { dayjs } from 'lib/dayjs'
import sortBy from 'lodash.sortby'

import { YC_BATCHES } from './constants'

/**
 * Generates YC batch options for the dropdown, showing relevant batches based on current date.
 *
 * - Sorts all batches by start date (newest first)
 * - Finds the current batch (most recent batch that has started)
 * - Returns current batch + all previous batches + 2 upcoming batches
 * - Adds placeholder at the top and "Earlier batches" at the bottom
 * - If all batches are in the future: returns first 2 batches only
 * - If current batch is among the first 2: starts from index 0 to avoid negative indices
 *
 * This logic should be kept in sync with the validation login in billing
 */
export function getYCBatchOptions(): { label: string; value: string }[] {
    // Sort batches by start date descending
    const sortedBatches = sortBy(YC_BATCHES, (batch) => dayjs(batch.start_date)).reverse()

    // Find current batch index (most recent batch where start date is in the past)
    const today = dayjs()
    const currentBatchIndex = sortedBatches.findIndex((batch) => dayjs(batch.start_date).isSameOrBefore(today))

    // If no current batch found (all batches are in future), start from first batch
    const startIndex = currentBatchIndex === -1 ? 0 : Math.max(0, currentBatchIndex - 2)

    // Take current + all previous + 2 upcoming batches
    const relevantBatches =
        currentBatchIndex === -1
            ? sortedBatches.slice(-2) // If all future, take last 2 (earliest batches but it's sorted newest-first)
            : sortedBatches.slice(startIndex) // From 2 upcoming through all previous

    const batchOptions = relevantBatches.map((batch) => ({
        label: batch.batch_name,
        value: batch.batch_name,
    }))

    return [{ label: 'Select your batch', value: '' }, ...batchOptions, { label: 'Earlier batches', value: 'Earlier' }]
}
