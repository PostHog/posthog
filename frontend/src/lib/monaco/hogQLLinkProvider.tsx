import { BuiltLogic } from 'kea'
import { languages } from 'monaco-editor'

import type { codeEditorLogicType } from './codeEditorLogicType'

export const hogQLLinkProvider: () => languages.LinkProvider = () => ({
    provideLinks: (model, _token) => {
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

        if (!viewMetadata || Object.keys(viewMetadata).length === 0) {
            return { links: [] }
        }

        const links: languages.ILink[] = []

        // Find all occurrences of view names in the query and create links
        for (const [viewName, viewInfo] of Object.entries(viewMetadata)) {
            const regex = new RegExp(`\\b${viewName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'gi')
            let match: RegExpExecArray | null

            while ((match = regex.exec(query)) !== null) {
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
                    tooltip: `Open ${viewInfo.is_materialized ? 'materialized view' : 'view'}: ${viewName}`,
                })
            }
        }

        return { links }
    },
    resolveLink: (link, _token) => {
        // The actual navigation will be handled by the editor's onMouseDown event
        return link
    },
})
