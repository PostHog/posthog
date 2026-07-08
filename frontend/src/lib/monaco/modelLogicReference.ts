import type { BuiltLogic } from 'kea'
import type { editor } from 'monaco-editor'

import type { codeEditorLogicType } from 'lib/monaco/codeEditorLogicType'

export function initModel(model: editor.ITextModel, builtCodeEditorLogic: BuiltLogic<codeEditorLogicType>): void {
    ;(model as any).codeEditorLogic = builtCodeEditorLogic
}

export function clearLogicReference(model: editor.ITextModel): void {
    ;(model as any).codeEditorLogic = undefined
}
