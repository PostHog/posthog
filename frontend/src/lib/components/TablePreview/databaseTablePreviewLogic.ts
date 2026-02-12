import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { hogqlQuery } from '~/queries/query'
import { hogql } from '~/queries/utils'

export interface DatabaseTablePreviewLogicProps {
    logicKey: string
    tableName?: string
    limit?: number
    whereClause?: string | null
}

const DEFAULT_LIMIT = 10

export const databaseTablePreviewLogic = kea([
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

                    try {
                        const response = await hogqlQuery(
                            trimmedWhereClause
                                ? hogql`SELECT * FROM ${hogql.identifier(props.tableName)} WHERE ${hogql.raw(trimmedWhereClause)} LIMIT ${previewLimit}`
                                : hogql`SELECT * FROM ${hogql.identifier(props.tableName)} LIMIT ${previewLimit}`
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
])
