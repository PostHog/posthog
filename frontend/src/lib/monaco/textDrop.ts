import { editor, IDisposable, IPosition, Range } from 'monaco-editor'

// Monaco's own drop handler inserts the dropped text as a snippet that ends in "$0". The standalone
// editor applies that edit as raw text and ignores the snippet flag, so every drop puts a literal
// "$0" into the document. Editors turn that handler off with `dropIntoEditor: { enabled: false }`
// and use this plain-text drop in its place.

const DROP_INDICATOR_CLASS = 'dnd-target'

function hasPlainText(event: DragEvent): boolean {
    return Array.from(event.dataTransfer?.types ?? []).includes('text/plain')
}

export function enablePlainTextDrop(editorInstance: editor.ICodeEditor): IDisposable {
    const domNode = editorInstance.getDomNode()
    if (!domNode) {
        return { dispose: () => {} }
    }
    const dropIndicator = editorInstance.createDecorationsCollection()

    const getDropPosition = (event: DragEvent): IPosition | null => {
        if (!hasPlainText(event) || editorInstance.getOption(editor.EditorOption.readOnly)) {
            return null
        }
        return editorInstance.getTargetAtClientPoint(event.clientX, event.clientY)?.position ?? null
    }

    const onDragOver = (event: DragEvent): void => {
        const position = getDropPosition(event)
        if (!position) {
            dropIndicator.clear()
            return
        }
        event.preventDefault()
        if (event.dataTransfer) {
            event.dataTransfer.dropEffect = 'copy'
        }
        dropIndicator.set([
            {
                range: new Range(position.lineNumber, position.column, position.lineNumber, position.column),
                options: { className: DROP_INDICATOR_CLASS },
            },
        ])
    }

    const onDrop = (event: DragEvent): void => {
        dropIndicator.clear()
        const position = getDropPosition(event)
        const model = editorInstance.getModel()
        const text = event.dataTransfer?.getData('text/plain')
        if (!position || !model || !text) {
            return
        }
        event.preventDefault()
        const range = new Range(position.lineNumber, position.column, position.lineNumber, position.column)
        editorInstance.pushUndoStop()
        editorInstance.executeEdits('plain-text-drop', [{ range, text, forceMoveMarkers: true }])
        editorInstance.pushUndoStop()
        editorInstance.setPosition(model.getPositionAt(model.getOffsetAt(position) + text.length))
        editorInstance.focus()
    }

    const onDragLeave = (): void => dropIndicator.clear()

    domNode.addEventListener('dragover', onDragOver)
    domNode.addEventListener('drop', onDrop)
    domNode.addEventListener('dragleave', onDragLeave)
    return {
        dispose: () => {
            domNode.removeEventListener('dragover', onDragOver)
            domNode.removeEventListener('drop', onDrop)
            domNode.removeEventListener('dragleave', onDragLeave)
            dropIndicator.clear()
        },
    }
}
