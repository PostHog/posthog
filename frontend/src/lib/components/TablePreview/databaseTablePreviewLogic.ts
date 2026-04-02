import { afterMount, kea, key, path, props, propsChanged, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { hogqlQuery } from '~/queries/query'
import { hogql } from '~/queries/utils'

import type { databaseTablePreviewLogicType } from './databaseTablePreviewLogicType'
import type { TablePreviewExpressionColumn } from './types'

export interface DatabaseTablePreviewLogicProps {
    logicKey: string
    tableName?: string
    limit?: number
    whereClause?: string | null
    expressionColumns?: TablePreviewExpressionColumn[]
}

const DEFAULT_LIMIT = 10

function buildPreviewQuery({
    tableName,
    limit,
    whereClause,
    expressionColumns,
}: Pick<DatabaseTablePreviewLogicProps, 'tableName' | 'limit' | 'whereClause' | 'expressionColumns'>): string | null {
    if (!tableName) {
        return null
    }

    const previewLimit = limit || DEFAULT_LIMIT
    const trimmedWhereClause = whereClause?.trim()
    const previewExpressionSelectClause =
        expressionColumns && expressionColumns.length > 0
            ? `, ${expressionColumns
                  .map(({ expression, key }) => String(hogql`${hogql.raw(expression)} AS ${hogql.identifier(key)}`))
                  .join(', ')}`
            : ''

    return String(
        trimmedWhereClause
            ? hogql`SELECT *${hogql.raw(previewExpressionSelectClause)} FROM ${hogql.identifier(tableName)} WHERE ${hogql.raw(trimmedWhereClause)} LIMIT ${previewLimit}`
            : hogql`SELECT *${hogql.raw(previewExpressionSelectClause)} FROM ${hogql.identifier(tableName)} LIMIT ${previewLimit}`
    )
}

export const databaseTablePreviewLogic = kea<databaseTablePreviewLogicType>([
    path((logicKey) => ['lib', 'components', 'TablePreview', 'databaseTablePreviewLogic', logicKey]),
    props({} as DatabaseTablePreviewLogicProps),
    key((props) => props.logicKey),
    selectors({
        previewQuery: [
            (s, p) => [p.tableName, p.limit, p.whereClause, p.expressionColumns],
            (tableName, limit, whereClause, expressionColumns): string | null =>
                buildPreviewQuery({ tableName, limit, whereClause, expressionColumns }),
        ],
    }),
    loaders(({ values }) => ({
        previewData: [
            [] as Record<string, any>[],
            {
                loadPreviewData: async () => {
                    if (!values.previewQuery) {
                        return []
                    }

                    try {
                        const response = await hogqlQuery(values.previewQuery)
                        return (response.results || []).map((row: any[]) =>
                            Object.fromEntries(
                                (response.columns || []).map((column: string, index: number) => [column, row[index]])
                            )
                        )
                    } catch (error) {
                        posthog.captureException(error)
                        return []
                    }
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadPreviewData()
    }),
    propsChanged(({ actions, props }, oldProps) => {
        if (buildPreviewQuery(props) !== buildPreviewQuery(oldProps)) {
            actions.loadPreviewData()
        }
    }),
])
