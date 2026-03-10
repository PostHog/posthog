import { afterMount, kea, key, path, props, propsChanged } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'

import { HogQLFilters, HogQLQueryModifiers, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

import type { databaseTablePreviewLogicType } from './databaseTablePreviewLogicType'
import type { TablePreviewExpressionColumn } from './types'

export interface DatabaseTablePreviewLogicProps {
    logicKey: string
    tableName?: string
    limit?: number
    whereClause?: string | null
    expressionColumns?: TablePreviewExpressionColumn[]
    queryFilters?: HogQLFilters
    queryModifiers?: HogQLQueryModifiers
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
                    const hasFilterContext = Boolean(props.queryFilters || props.queryModifiers)
                    const forwardedQueryFilters = props.queryFilters ?? {}
                    const baseQuery = String(
                        hogql`SELECT *${hogql.raw(previewExpressionSelectClause)} FROM ${hogql.identifier(props.tableName)}`
                    )
                    const previewQuery = hasFilterContext
                        ? `${baseQuery}${
                              trimmedWhereClause ? ` WHERE {filters} AND (${trimmedWhereClause})` : ' WHERE {filters}'
                          } LIMIT ${previewLimit}`
                        : String(
                              trimmedWhereClause
                                  ? hogql`${hogql.raw(baseQuery)} WHERE ${hogql.raw(trimmedWhereClause)} LIMIT ${previewLimit}`
                                  : hogql`${hogql.raw(baseQuery)} LIMIT ${previewLimit}`
                          )

                    try {
                        const response = (await api.query({
                            kind: NodeKind.HogQLQuery,
                            query: previewQuery,
                            filters: hasFilterContext ? forwardedQueryFilters : undefined,
                            modifiers: props.queryModifiers,
                        })) as HogQLQueryResponse

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
        const previousQueryFilters = JSON.stringify(oldProps.queryFilters || null)
        const nextQueryFilters = JSON.stringify(props.queryFilters || null)
        const previousQueryModifiers = JSON.stringify(oldProps.queryModifiers || null)
        const nextQueryModifiers = JSON.stringify(props.queryModifiers || null)

        if (
            props.tableName !== oldProps.tableName ||
            previousWhereClause !== nextWhereClause ||
            previousLimit !== nextLimit ||
            previousExpressionColumns !== nextExpressionColumns ||
            previousQueryFilters !== nextQueryFilters ||
            previousQueryModifiers !== nextQueryModifiers
        ) {
            actions.loadPreviewData()
        }
    }),
])
