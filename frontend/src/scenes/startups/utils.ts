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
 *
 * This logic should be kept in sync with the validation login in billing
 */
export function getYCBatchOptions(): { label: string; value: string }[] {
    // Sort batches by start date descending
    const sortedBatches = sortBy(YC_BATCHES, (batch) => dayjs(batch.start_date)).reverse()

    // Find current batch index (most recent batch where start date is in the past)
    const today = dayjs()
    const currentBatchIndex = sortedBatches.findIndex((batch) => dayjs(batch.start_date).isSameOrBefore(today))

    // Start from 2 batches before current (or from beginning if current is early)
    const startIndex = Math.max(0, currentBatchIndex - 2)

    // Take from 2 upcoming through all previous batches
    const relevantBatches = sortedBatches.slice(startIndex)

    const batchOptions = relevantBatches.map((batch) => ({
        label: batch.batch_name,
        value: batch.batch_name,
    }))

    return [{ label: 'Select your batch', value: '' }, ...batchOptions, { label: 'Earlier batches', value: 'Earlier' }]
}
