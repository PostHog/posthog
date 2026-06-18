import type { InsightEditorFilterGroup, InsightLogicProps } from '~/types'

import { EditorFilterGroupTile } from './EditorFilterGroupTile'

export interface EditorFilterGroupProps {
    editorFilterGroup: InsightEditorFilterGroup
    insightProps: InsightLogicProps
    queryKind?: string
}

export function EditorFilterGroup({ insightProps, editorFilterGroup, queryKind }: EditorFilterGroupProps): JSX.Element {
    return (
        <EditorFilterGroupTile
            insightProps={insightProps}
            editorFilterGroup={editorFilterGroup}
            queryKind={queryKind}
        />
    )
}
