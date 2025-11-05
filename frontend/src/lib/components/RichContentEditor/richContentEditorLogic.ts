import { kea, key, path, props, selectors } from 'kea'

import type { richContentEditorLogicType } from './richContentEditorLogicType'
import { RichContentEditorType, TTEditor } from './types'
import { createEditor } from './utils'

export interface RichContentEditorLogicProps {
    logicKey: string
    editor: TTEditor
}

export const richContentEditorLogic = kea<richContentEditorLogicType>([
    path(['lib', 'components', 'RichContentEditor', 'richContentEditorLogic']),
    props({} as RichContentEditorLogicProps),
    key(({ logicKey }) => `RichContentEditor.${logicKey}`),
    selectors({
        ttEditor: [(_, p) => [p.editor], (editor): TTEditor => editor],
        richContentEditor: [(s) => [s.ttEditor], (ttEditor): RichContentEditorType => createEditor(ttEditor)],
    }),
])
