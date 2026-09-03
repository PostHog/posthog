import { JSONContent } from '@tiptap/core'

import { parseMarkdownNotebook, serializeMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import { NotebookBlockNode, NotebookComponentProps } from 'lib/components/MarkdownNotebook/types'
import { uuid } from 'lib/utils/dom'
import { NotebookNodeType } from 'scenes/notebooks/types'

// The removed code cells (in-browser-kernel Python, DuckDB SQL, HogQL SQL) and the sandbox-kernel
// cell each one becomes. The legacy SQL cells named their dataframe `duck_df` / `hogql_df` when the
// author never set a name, so that default is written out to keep downstream references working.
//
// A DuckSQL cell also changes dialect. SQLV2 picks its engine per run: it goes to DuckDB only when
// the query reads a frame that a Python cell made, and to HogQL against ClickHouse otherwise. So a
// converted DuckSQL cell that used DuckDB-only syntax reports a query error until its author adapts
// the code. That is still better than skipping the conversion, because an unconverted legacy tag
// renders as an unknown component and cannot run at all.
const LEGACY_CODE_CELL_TAGS: Record<string, { tagName: string; defaultReturnVariable: string | null }> = {
    Python: { tagName: 'PythonV2', defaultReturnVariable: null },
    DuckSQL: { tagName: 'SQLV2', defaultReturnVariable: 'duck_df' },
    HogQLSQL: { tagName: 'SQLV2', defaultReturnVariable: 'hogql_df' },
}

function convertLegacyCodeCell(node: NotebookBlockNode): NotebookBlockNode {
    if (node.type !== 'component' || node.errors?.length) {
        return node
    }
    const target = LEGACY_CODE_CELL_TAGS[node.tagName]
    if (!target) {
        return node
    }

    // Only the code and its name carry over. The legacy execution results were bound to a kernel
    // sandbox that no longer exists, so the cell opens on its code and runs from scratch.
    const props: NotebookComponentProps = {
        nodeId: typeof node.props.nodeId === 'string' && node.props.nodeId ? node.props.nodeId : uuid(),
        code: typeof node.props.code === 'string' ? node.props.code : '',
        showFilters: true,
    }
    if (typeof node.props.title === 'string' && node.props.title) {
        props.title = node.props.title
    }
    if (target.defaultReturnVariable !== null) {
        props.returnVariable =
            typeof node.props.returnVariable === 'string' && node.props.returnVariable.trim()
                ? node.props.returnVariable
                : target.defaultReturnVariable
    }
    return { id: node.id, type: 'component', tagName: target.tagName, props, startsGroup: node.startsGroup }
}

function convertLegacyCodeCellsInMarkdown(markdown: string): string {
    const document = parseMarkdownNotebook(markdown)
    let changed = false
    const nodes = document.nodes.map((node) => {
        const converted = convertLegacyCodeCell(node)
        changed = changed || converted !== node
        return converted
    })
    // Re-serializing is only worth the risk of touching unrelated formatting when a cell changed.
    return changed ? serializeMarkdownNotebook({ ...document, nodes }) : markdown
}

export function convertLegacyCodeCellsInContent(content: JSONContent[]): JSONContent[] {
    return content.map((node) => {
        if (node.type !== NotebookNodeType.MarkdownNotebook || typeof node.attrs?.markdown !== 'string') {
            return node
        }
        const markdown = convertLegacyCodeCellsInMarkdown(node.attrs.markdown)
        return markdown === node.attrs.markdown ? node : { ...node, attrs: { ...node.attrs, markdown } }
    })
}
