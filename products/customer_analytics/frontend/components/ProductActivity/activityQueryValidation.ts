import type { HogQLQueryResponse } from '~/queries/schema/schema-general'

import { DOT_MATRIX_CONFIG_MAX_BYTES, getDotMatrixConfigBytes, type DotMatrixTileSource } from './dotMatrixTileConfig'
import { getHogQLActivityMatrix } from './hogqlActivityMatrix'

export function getActivityQuerySaveError({
    scope,
    loading,
    error,
    source,
    resultSource,
    result,
    config,
}: {
    scope: 'account' | 'book'
    loading: boolean
    error: string | null
    source: DotMatrixTileSource
    resultSource: DotMatrixTileSource | null
    result: HogQLQueryResponse | null
    config: Record<string, unknown>
}): string | null {
    if (loading) {
        return 'Wait for the query to finish.'
    }
    const excess = getDotMatrixConfigBytes(config) - DOT_MATRIX_CONFIG_MAX_BYTES
    if (scope === 'account' && excess > 0) {
        return `This query is too long to save. Remove about ${excess} characters.`
    }
    if (error && scope === 'book') {
        return 'Fix the query error and run it again.'
    }
    if (
        error ||
        !resultSource ||
        resultSource.kind !== source.kind ||
        (source.kind === 'hogql' && (resultSource.kind !== 'hogql' || resultSource.query !== source.query))
    ) {
        return scope === 'account' ? 'Run the query before saving.' : 'Run this query before saving.'
    }
    if (excess > 0) {
        return 'The query is too large to save. Shorten it and run it again.'
    }
    if (source.kind !== 'hogql') {
        return null
    }
    if (!result) {
        return 'No accounts match. Change the filters and run the query.'
    }
    return getHogQLActivityMatrix(result, source.mapping).error
}
