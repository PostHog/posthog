import { BuiltLogic } from 'kea'
import { languages } from 'monaco-editor'

import type { codeEditorLogicType } from './codeEditorLogicType'

export const hogQLLinkProvider: () => languages.LinkProvider = () => ({
    provideLinks: (model) => {
        const logic: BuiltLogic<codeEditorLogicType> | undefined = (model as any).codeEditorLogic
        if (!logic?.isMounted()) {
            return { links: [] }
        }

        const metadata = logic.values.metadata
        if (!metadata) {
            return { links: [] }
        }

        const [query, metadataResponse] = metadata
        const viewMetadata = metadataResponse?.view_metadata
        const tableNames = metadataResponse?.table_names

        if (!viewMetadata || Object.keys(viewMetadata).length === 0 || !tableNames) {
            return { links: [] }
        }

        const links: languages.ILink[] = []

        // Only create links for tables that are actually in the query
        for (const tableName of tableNames) {
            const viewInfo = viewMetadata[tableName]
            if (!viewInfo) {
                // This table is not a view, skip it
                continue
            }

            // Find all exact occurrences of this specific table name in the query
            const regex = new RegExp(`\\b${tableName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'gi')

            for (const match of query.matchAll(regex)) {
                if (match.index === undefined) {
                    continue
                }

                const startPos = model.getPositionAt(match.index)
                const endPos = model.getPositionAt(match.index + match[0].length)

                links.push({
                    range: {
                        startLineNumber: startPos.lineNumber,
                        startColumn: startPos.column,
                        endLineNumber: endPos.lineNumber,
                        endColumn: endPos.column,
                    },
                    url: `#view:${viewInfo.id}`,
                    tooltip: `Open ${viewInfo.is_materialized ? 'materialized view' : 'view'}: ${tableName} in new tab`,
                })
                break
            }
        }

        return { links }
    },
    resolveLink: (link) => {
        // The actual navigation will be handled by the editor's onMouseDown event
        return link
    },
})
