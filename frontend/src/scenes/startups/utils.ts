import sortBy from 'lodash.sortby'

import { dayjs } from 'lib/dayjs'

import { YC_BATCHES } from './constants'

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
