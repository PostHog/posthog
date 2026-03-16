import { afterMount, kea, key, path, props, propsChanged } from 'kea'
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

export const databaseTablePreviewLogic = kea<databaseTablePreviewLogicType>([
    path((logicKey) => ['lib', 'components', 'TablePreview', 'databaseTablePreviewLogic', logicKey]),
    props({} as DatabaseTablePreviewLogicProps),
    key((props) => props.logicKey),
    loaders(({ props }) => ({
        previewData: [
            [] as Record<string, any>[],
            {
                loadPreviewData: async () => {
                    if (!props.tableName) {
                        return []
                    }

                    const previewLimit = props.limit || DEFAULT_LIMIT
                    const trimmedWhereClause = props.whereClause?.trim()
                    const previewExpressionSelectClause =
                        props.expressionColumns && props.expressionColumns.length > 0
                            ? `, ${props.expressionColumns
                                  .map(({ expression, key }) =>
                                      String(hogql`${hogql.raw(expression)} AS ${hogql.identifier(key)}`)
                                  )
                                  .join(', ')}`
                            : ''

                    try {
                        const response = await hogqlQuery(
                            trimmedWhereClause
                                ? hogql`SELECT *${hogql.raw(previewExpressionSelectClause)} FROM ${hogql.identifier(props.tableName)} WHERE ${hogql.raw(trimmedWhereClause)} LIMIT ${previewLimit}`
                                : hogql`SELECT *${hogql.raw(previewExpressionSelectClause)} FROM ${hogql.identifier(props.tableName)} LIMIT ${previewLimit}`
                        )
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
        const previousWhereClause = oldProps.whereClause?.trim() || null
        const nextWhereClause = props.whereClause?.trim() || null
        const previousLimit = oldProps.limit || DEFAULT_LIMIT
        const nextLimit = props.limit || DEFAULT_LIMIT
        const previousExpressionColumns = JSON.stringify(oldProps.expressionColumns || [])
        const nextExpressionColumns = JSON.stringify(props.expressionColumns || [])

        if (
            props.tableName !== oldProps.tableName ||
            previousWhereClause !== nextWhereClause ||
            previousLimit !== nextLimit ||
            previousExpressionColumns !== nextExpressionColumns
        ) {
            actions.loadPreviewData()
        }
    }),
])
