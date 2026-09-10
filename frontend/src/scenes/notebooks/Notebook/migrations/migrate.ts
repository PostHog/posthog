import { JSONContent } from '@tiptap/core'

import api from 'lib/api'
import { NotebookNodePlaylistAttributes } from 'scenes/notebooks/Nodes/NotebookNodePlaylist'
import { NotebookNodeType, NotebookType } from 'scenes/notebooks/types'
import { convertLegacyFiltersToUniversalFilters } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { checkLatestVersionsOnQuery } from '~/queries/utils'
import { LegacyRecordingFilters } from '~/types'

import { convertMarkdownTablesInContent } from './convertMarkdownTablesInContent'

// NOTE: Increment this number when you add a new content migration
// It will bust the cache on the localContent in the notebookLogic
// so that the latest content will fall back to the remote content which
// is filtered through the migrate function below that ensures integrity
export const NOTEBOOKS_VERSION = '3'

export interface MigrateOptions {
    /**
     * Skips the query migrate step which issues a POST request to the backend which will result
     * in a 403 error for unauthenticated users viewing a shared notebook.
     */
    skipApiUpgrade?: boolean
}

export async function migrate(notebook: NotebookType, options: MigrateOptions = {}): Promise<NotebookType> {
    let content = notebook.content?.content

    if (!content) {
        return notebook
    }

    content = convertInsightToQueryNode(content)
    content = convertInsightQueryStringsToObjects(content)
    content = convertPlaylistFiltersToUniversalFilters(content)
    content = convertMarkdownTablesInContent(content)
    if (!options.skipApiUpgrade) {
        content = await upgradeQueryNode(content)
    }

    return { ...notebook, content: { type: 'doc', content: content } }
}

function convertPlaylistFiltersToUniversalFilters(content: JSONContent[]): JSONContent[] {
    return content.map((node) => {
        if (node.type != NotebookNodeType.RecordingPlaylist) {
            return node
        }

        // Legacy attrs on Notebook playlist nodes
        const simpleFilters = node.attrs?.simpleFilters as LegacyRecordingFilters
        const filters = node.attrs?.filters as LegacyRecordingFilters

        const { universalFilters } = node.attrs as NotebookNodePlaylistAttributes

        if (universalFilters) {
            return node
        }

        const jsonFilters = typeof filters === 'string' ? JSON.parse(filters) : filters
        const jsonSimpleFilters = typeof simpleFilters === 'string' ? JSON.parse(simpleFilters) : simpleFilters

        const jsonUniversalFilters = convertLegacyFiltersToUniversalFilters(jsonSimpleFilters, jsonFilters)

        return {
            ...node,
            attrs: {
                ...node.attrs,
                universalFilters: JSON.stringify(jsonUniversalFilters),
            },
        }
    })
}

function convertInsightToQueryNode(content: JSONContent[]): JSONContent[] {
    return content.map((node) => {
        if (node.type != 'ph-insight') {
            return node
        }

        return {
            ...node,
            type: NotebookNodeType.Query,
            attrs: {
                nodeId: node.attrs?.nodeId,
                query: { kind: NodeKind.SavedInsightNode, shortId: node.attrs?.id },
            },
        }
    })
}

function convertInsightQueryStringsToObjects(content: JSONContent[]): JSONContent[] {
    return content.map((node) => {
        if (
            !(
                node.type == NotebookNodeType.Query &&
                node.attrs &&
                'query' in node.attrs &&
                typeof node.attrs.query === 'string'
            )
        ) {
            return node
        }

        let query

        try {
            query = JSON.parse(node.attrs.query)
        } catch {
            query = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'person', 'timestamp'],
                    orderBy: ['timestamp DESC'],
                    after: '-24h',
                    limit: 100,
                },
            }
        }

        return {
            ...node,
            attrs: {
                ...node.attrs,
                query,
            },
        }
    })
}

async function upgradeQueryNode(content: JSONContent[]): Promise<JSONContent[]> {
    return Promise.all(
        content.map(async (node) => {
            if (
                node.type !== NotebookNodeType.Query ||
                !node.attrs ||
                !('query' in node.attrs) ||
                node.attrs.query.kind === NodeKind.SavedInsightNode
            ) {
                return node
            }

            const query = node.attrs.query

            if (checkLatestVersionsOnQuery(query)) {
                return node
            }

            const response = await api.schema.queryUpgrade({ query })
            return {
                ...node,
                attrs: {
                    ...node.attrs,
                    query: response.query,
                },
            }
        })
    )
}
