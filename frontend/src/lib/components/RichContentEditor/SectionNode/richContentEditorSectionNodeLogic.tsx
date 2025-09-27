import { kea, key, path, props, selectors } from 'kea'

import type { richContentEditorSectionNodeLogicType } from './richContentEditorSectionNodeLogicType'

export interface RichContentEditorSectionNodeLogicProps {
    id: string
    open: boolean
}

export const richContentEditorSectionNodeLogic = kea<richContentEditorSectionNodeLogicType>([
    path(['components', 'RichContentEditor', 'sectionNode', 'richContentEditorSectionNodeLogic']),
    key((props) => props.id),
    props({} as RichContentEditorSectionNodeLogicProps),

    selectors({
        open: [
            (_, p) => [p.open],
            (open) => {
                debugger
                return open
            },
        ],
    }),
])
