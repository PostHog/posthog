import { isNativeEditableElement } from './domSelection'

function elementForNode(node: Node): Element | null {
    return node instanceof Element ? node : node.parentElement
}

function caretAtPoint(document: Document, x: number, y: number): Range | null {
    const caretDocument = document as Document & {
        caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null
        caretRangeFromPoint?: (x: number, y: number) => Range | null
    }
    const position = caretDocument.caretPositionFromPoint?.(x, y)
    if (position) {
        const range = document.createRange()
        range.setStart(position.offsetNode, position.offset)
        range.collapse(true)
        return range
    }
    return caretDocument.caretRangeFromPoint?.(x, y) ?? null
}

export function installNotebookTextSelection(canvas: HTMLElement): () => void {
    const document = canvas.ownerDocument
    const window = document.defaultView!
    let startRow: Element | null = null
    let anchor: Range | null = null
    let frame: number | null = null
    let pendingUpdate: (() => void) | null = null
    let crossedRows = false

    const stop = (): void => {
        startRow = null
        anchor = null
        pendingUpdate = null
        crossedRows = false
        if (frame !== null) {
            window.cancelAnimationFrame(frame)
            frame = null
        }
    }

    const onMouseDown = (event: MouseEvent): void => {
        stop()
        const target = event.target
        if (
            event.button !== 0 ||
            !(target instanceof HTMLElement) ||
            isNativeEditableElement(target) ||
            target.closest('button, a, [role="button"], [draggable="true"]')
        ) {
            return
        }
        startRow = target.closest('.MarkdownNotebook__row')
    }

    const onMouseMove = (event: MouseEvent): void => {
        if (!startRow || !(event.buttons & 1)) {
            return
        }
        const selection = window.getSelection()
        if (!anchor && selection?.anchorNode && startRow.contains(selection.anchorNode)) {
            anchor = document.createRange()
            anchor.setStart(selection.anchorNode, selection.anchorOffset)
            anchor.collapse(true)
        }
        const focus = caretAtPoint(document, event.clientX, event.clientY)
        if (!anchor || !focus || !canvas.contains(focus.startContainer)) {
            return
        }
        const focusRow = elementForNode(focus.startContainer)?.closest('.MarkdownNotebook__row')
        if (!focusRow || (focusRow === startRow && !crossedRows)) {
            if (frame !== null) {
                window.cancelAnimationFrame(frame)
                frame = null
                pendingUpdate = null
            }
            return
        }
        crossedRows ||= focusRow !== startRow

        const backwards = anchor.compareBoundaryPoints(Range.START_TO_START, focus) > 0
        const range = document.createRange()
        const start = backwards ? focus : anchor
        const end = backwards ? anchor : focus
        range.setStart(start.startContainer, start.startOffset)
        range.setEnd(end.startContainer, end.startOffset)
        const startComponent = elementForNode(range.startContainer)?.closest('.MarkdownNotebook__component-shell')
        const endComponent = elementForNode(range.endContainer)?.closest('.MarkdownNotebook__component-shell')
        if (startComponent && focusRow !== startRow) {
            range.setStartBefore(startComponent)
        }
        if (endComponent && focusRow !== startRow) {
            range.setEndAfter(endComponent)
        }

        // Native dragging stops at contenteditable=false cell boundaries. Apply the notebook range
        // after the browser's default selection update, with crossed components selected as blocks.
        if (frame !== null) {
            window.cancelAnimationFrame(frame)
        }
        pendingUpdate = () => {
            canvas.focus({ preventScroll: true })
            selection?.setBaseAndExtent(
                backwards ? range.endContainer : range.startContainer,
                backwards ? range.endOffset : range.startOffset,
                backwards ? range.startContainer : range.endContainer,
                backwards ? range.startOffset : range.endOffset
            )
        }
        frame = window.requestAnimationFrame(() => {
            frame = null
            pendingUpdate?.()
            pendingUpdate = null
        })
    }

    const onMouseUp = (): void => {
        pendingUpdate?.()
        stop()
    }

    canvas.addEventListener('mousedown', onMouseDown)
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    document.addEventListener('dragstart', stop)
    window.addEventListener('blur', stop)
    return () => {
        stop()
        canvas.removeEventListener('mousedown', onMouseDown)
        document.removeEventListener('mousemove', onMouseMove)
        document.removeEventListener('mouseup', onMouseUp)
        document.removeEventListener('dragstart', stop)
        window.removeEventListener('blur', stop)
    }
}
