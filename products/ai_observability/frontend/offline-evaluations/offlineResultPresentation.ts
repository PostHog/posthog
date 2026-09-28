import { ApiError } from 'lib/api-error'

import type {
    OfflineEvaluationErrorApi,
    OfflineResultCellApi,
    OfflineResultReadApi,
    OfflineScorerVersionReadApi,
} from '../generated/api.schemas'
import { getBooleanConfig, getCategoricalConfig } from '../scoreDefinitions/scoreDefinitionConfigUtils'
import { formatOfflineNumericScore } from './offlineScoreTrends'

export function offlineResultLabel(
    result: OfflineResultCellApi | OfflineResultReadApi,
    scorer: OfflineScorerVersionReadApi
): string {
    if (result.status !== 'ok') {
        return { error: 'Error', skipped: 'Skipped', not_applicable: 'Not applicable' }[result.status]
    }
    if (typeof result.value === 'number') {
        return formatOfflineNumericScore(result.value)
    }
    if (typeof result.value === 'boolean') {
        const config = getBooleanConfig(scorer.config)
        return result.value ? config.true_label || 'True' : config.false_label || 'False'
    }
    if (Array.isArray(result.value)) {
        const options = getCategoricalConfig(scorer.config).options
        return (
            result.value.map((value) => options.find((option) => option.key === value)?.label || value).join(', ') ||
            'No categories'
        )
    }
    return 'No value'
}

export function offlineReadError(error: unknown, fallback: string): string {
    if (error instanceof ApiError) {
        if (error.status === 404) {
            return 'This resource is unavailable or you do not have access.'
        }
        if (error.status === 403) {
            return error.detail || 'You do not have access to this data.'
        }
        if (error.status === 429) {
            return `Too many requests. Try again${error.formattedRetryAfter ? ` in ${error.formattedRetryAfter}` : ' shortly'}.`
        }
        return error.detail || fallback
    }
    return fallback
}

export function offlineCompletionError(error: unknown): string {
    if (error instanceof ApiError && error.code === 'expected_count_mismatch') {
        const data = error.data as OfflineEvaluationErrorApi
        const excess =
            (data.expected_item_count !== null &&
                data.expected_item_count !== undefined &&
                (data.accepted_item_count || 0) > data.expected_item_count) ||
            (data.expected_result_count !== null &&
                data.expected_result_count !== undefined &&
                (data.accepted_result_count || 0) > data.expected_result_count)
        return `Accepted items: ${data.accepted_item_count ?? 'unknown'}; expected: ${data.expected_item_count ?? 'not specified'}. Accepted results: ${data.accepted_result_count ?? 'unknown'}; expected: ${data.expected_result_count ?? 'not specified'}. ${excess ? 'Accepted counts exceed the declaration. Uploading more cannot resolve this, and declared expectations cannot be edited.' : 'Resume missing uploads before marking this experiment as completed.'}`
    }
    return offlineReadError(error, 'Could not complete this experiment. Refresh its state and try again.')
}
