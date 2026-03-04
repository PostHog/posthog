import { Extension } from '@tiptap/core'
import { Node as ProseMirrorNode } from '@tiptap/pm/model'
import { EditorState, NodeSelection, Plugin, PluginKey, Transaction } from '@tiptap/pm/state'
import { Decoration, DecorationSet, EditorView } from '@tiptap/pm/view'

const pluginKey = new PluginKey<DragFeedbackState>('formDragFeedback')
const SLOT_HEIGHT = 48

interface DragFeedbackState {
    isDragging: boolean
    draggedPos: number | null
    slotPos: number | null
    slotGapIndex: number | null
}

const DEFAULT_STATE: DragFeedbackState = {
    isDragging: false,
    draggedPos: null,
    slotPos: null,
    slotGapIndex: null,
}

function getPluginState(view: EditorView): DragFeedbackState {
    return pluginKey.getState(view.state) ?? DEFAULT_STATE
}

function getTopLevelBlocks(view: EditorView): HTMLElement[] {
    return Array.from(view.dom.children).filter((node): node is HTMLElement => {
        if (!(node instanceof HTMLElement)) {
            return false
        }

        if (node.classList.contains('ProseMirror-widget')) {
            return false
        }

        if (node.classList.contains('node-formButton')) {
            return false
        }

        return true
    })
}

function getTopLevelBlockIndexAtPos(view: EditorView, pos: number, blocks: HTMLElement[]): number {
    let dom: Node | null = view.nodeDOM(pos)

    while (dom && dom.parentNode !== view.dom) {
        dom = dom.parentNode
    }

    if (dom instanceof HTMLElement) {
        return blocks.indexOf(dom)
    }

    return -1
}

function getGapTopY(blocks: HTMLElement[], gapIndex: number): number {
    if (gapIndex <= 0) {
        return blocks[0].getBoundingClientRect().top
    }

    const aboveIndex = Math.min(gapIndex - 1, blocks.length - 1)
    return blocks[aboveIndex].getBoundingClientRect().bottom
}

function getGapCenterY(blocks: HTMLElement[], gapIndex: number): number {
    if (gapIndex <= 0) {
        return blocks[0].getBoundingClientRect().top
    }

    if (gapIndex >= blocks.length) {
        return blocks[blocks.length - 1].getBoundingClientRect().bottom
    }

    const aboveBottom = blocks[gapIndex - 1].getBoundingClientRect().bottom
    const belowTop = blocks[gapIndex].getBoundingClientRect().top

    return (aboveBottom + belowTop) / 2
}

function findNearestGapIndex(blocks: HTMLElement[], mouseY: number): number {
    let closest = { index: 0, distance: Infinity }

    for (let index = 0; index <= blocks.length; index++) {
        const gapY = getGapCenterY(blocks, index)
        const distance = Math.abs(mouseY - gapY)

        if (distance < closest.distance) {
            closest = { index, distance }
        }
    }

    return closest.index
}

function isPointInGapSlot(blocks: HTMLElement[], gapIndex: number, mouseY: number): boolean {
    const slotTop = getGapTopY(blocks, gapIndex)
    const slotBottom = slotTop + SLOT_HEIGHT

    return mouseY >= slotTop - 8 && mouseY <= slotBottom + 8
}

function getTopLevelBoundaryStartFromDoc(doc: ProseMirrorNode, pos: number): number {
    const clampedPos = Math.max(0, Math.min(pos, doc.content.size))
    const $pos = doc.resolve(clampedPos)

    if ($pos.depth === 0) {
        return $pos.pos
    }

    return $pos.before(1)
}

function getTopLevelBoundaryStart(view: EditorView, pos: number): number {
    return getTopLevelBoundaryStartFromDoc(view.state.doc, pos)
}

function getTopLevelStartPosFromBlock(view: EditorView, block: HTMLElement): number | null {
    try {
        const pos = view.posAtDOM(block, 0)
        return getTopLevelBoundaryStart(view, pos)
    } catch {
        return null
    }
}

function getDropPosFromGapIndex(view: EditorView, gapIndex: number, blocks: HTMLElement[]): number | null {
    if (gapIndex < 0 || blocks.length === 0) {
        return null
    }

    if (gapIndex === 0) {
        return getTopLevelStartPosFromBlock(view, blocks[0])
    }

    if (gapIndex < blocks.length) {
        return getTopLevelStartPosFromBlock(view, blocks[gapIndex])
    }

    const lastBlockStart = getTopLevelStartPosFromBlock(view, blocks[blocks.length - 1])
    if (lastBlockStart === null) {
        return null
    }

    const lastNode = view.state.doc.nodeAt(lastBlockStart)
    if (!lastNode) {
        return null
    }

    return lastBlockStart + lastNode.nodeSize
}

function sameState(left: DragFeedbackState, right: DragFeedbackState): boolean {
    return (
        left.isDragging === right.isDragging &&
        left.draggedPos === right.draggedPos &&
        left.slotPos === right.slotPos &&
        left.slotGapIndex === right.slotGapIndex
    )
}

function setDragState(view: EditorView, patch: Partial<DragFeedbackState>): void {
    const current = getPluginState(view)
    const next = { ...current, ...patch }

    if (sameState(current, next)) {
        return
    }

    view.dispatch(view.state.tr.setMeta(pluginKey, next))
}

function clearDragState(view: EditorView): void {
    view.dom.classList.remove('dragging')
    setDragState(view, DEFAULT_STATE)
}

function createDropSlotElement(): HTMLElement {
    const element = document.createElement('div')
    element.className = 'form-drop-slot-widget'
    element.textContent = 'Drop here'
    element.contentEditable = 'false'
    return element
}

function mapPos(position: number | null, transaction: Transaction): number | null {
    if (position === null) {
        return null
    }

    return transaction.mapping.map(position)
}

function getDropSlotDecorations(state: DragFeedbackState, editorState: EditorState): DecorationSet {
    if (!state.isDragging) {
        return DecorationSet.empty
    }

    const decorations: Decoration[] = []

    if (state.draggedPos !== null) {
        const draggedPos = getTopLevelBoundaryStartFromDoc(editorState.doc, state.draggedPos)
        const draggedNode = editorState.doc.nodeAt(draggedPos)

        if (draggedNode && draggedNode.type.name !== 'formButton') {
            decorations.push(
                Decoration.node(draggedPos, draggedPos + draggedNode.nodeSize, {
                    class: 'form-dragging-source',
                })
            )
        }
    }

    if (state.slotPos !== null) {
        decorations.push(
            Decoration.widget(state.slotPos, createDropSlotElement, {
                key: `form-drop-slot-${state.slotPos}`,
                side: -1,
            })
        )
    }

    if (decorations.length === 0) {
        return DecorationSet.empty
    }

    return DecorationSet.create(editorState.doc, decorations)
}

export const FormDragFeedback = Extension.create({
    name: 'formDragFeedback',

    addProseMirrorPlugins() {
        return [
            new Plugin<DragFeedbackState>({
                key: pluginKey,
                state: {
                    init: () => DEFAULT_STATE,
                    apply(transaction, pluginState) {
                        const meta = transaction.getMeta(pluginKey) as DragFeedbackState | undefined
                        const nextState = meta ?? pluginState

                        if (!transaction.docChanged) {
                            return nextState
                        }

                        return {
                            ...nextState,
                            draggedPos: mapPos(nextState.draggedPos, transaction),
                            slotPos: mapPos(nextState.slotPos, transaction),
                        }
                    },
                },
                props: {
                    decorations(state) {
                        const pluginState = pluginKey.getState(state) ?? DEFAULT_STATE
                        return getDropSlotDecorations(pluginState, state)
                    },
                    handleDrop(view, _event, _slice, moved) {
                        const pluginState = getPluginState(view)
                        const { draggedPos, slotPos } = pluginState

                        if (!moved || draggedPos === null || slotPos === null) {
                            clearDragState(view)
                            return false
                        }

                        const normalizedDraggedPos = getTopLevelBoundaryStart(view, draggedPos)
                        const draggedNode = view.state.doc.nodeAt(normalizedDraggedPos)

                        if (!draggedNode) {
                            clearDragState(view)
                            return true
                        }

                        const dragEnd = normalizedDraggedPos + draggedNode.nodeSize
                        const titleEnd = view.state.doc.firstChild?.nodeSize ?? 0

                        if (slotPos < titleEnd || (slotPos >= normalizedDraggedPos && slotPos <= dragEnd)) {
                            clearDragState(view)
                            return true
                        }

                        const transaction = view.state.tr
                        transaction.delete(normalizedDraggedPos, dragEnd)
                        const mappedDropPos = transaction.mapping.map(slotPos)
                        transaction.insert(mappedDropPos, draggedNode.copy(draggedNode.content))

                        try {
                            transaction.setSelection(NodeSelection.create(transaction.doc, mappedDropPos))
                        } catch {
                            // NodeSelection may fail for non-atom nodes.
                        }

                        transaction.setMeta(pluginKey, DEFAULT_STATE)
                        view.dom.classList.remove('dragging')
                        view.dispatch(transaction)

                        return true
                    },
                    handleDOMEvents: {
                        dragstart(view) {
                            view.dom.classList.add('dragging')
                            const selection = view.state.selection
                            const selectionPos = selection instanceof NodeSelection ? selection.from : selection.from
                            const draggedPos = getTopLevelBoundaryStart(view, selectionPos)

                            setDragState(view, {
                                isDragging: true,
                                draggedPos,
                                slotPos: null,
                                slotGapIndex: null,
                            })

                            return false
                        },
                        dragover(view, event) {
                            if (!view.dragging) {
                                return false
                            }

                            view.dom.classList.add('dragging')

                            const pluginState = getPluginState(view)
                            const fallbackDraggedPos = getTopLevelBoundaryStart(view, view.state.selection.from)
                            let draggedPos = pluginState.draggedPos ?? fallbackDraggedPos
                            const draggedNode = view.state.doc.nodeAt(draggedPos)

                            if (!draggedNode || !draggedNode.isBlock) {
                                draggedPos = fallbackDraggedPos
                            }

                            const blocks = getTopLevelBlocks(view)
                            if (blocks.length === 0) {
                                return false
                            }

                            let gapIndex = findNearestGapIndex(blocks, event.clientY)

                            if (gapIndex === 0) {
                                gapIndex = 1
                            }

                            if (
                                pluginState.slotGapIndex !== null &&
                                pluginState.slotGapIndex > 0 &&
                                pluginState.slotGapIndex <= blocks.length &&
                                isPointInGapSlot(blocks, pluginState.slotGapIndex, event.clientY)
                            ) {
                                gapIndex = pluginState.slotGapIndex
                            }

                            const draggedBlockIndex = getTopLevelBlockIndexAtPos(view, draggedPos, blocks)
                            const isNoOp =
                                draggedBlockIndex >= 0 &&
                                (gapIndex === draggedBlockIndex || gapIndex === draggedBlockIndex + 1)

                            let slotPos = isNoOp ? null : getDropPosFromGapIndex(view, gapIndex, blocks)

                            const titleEnd = view.state.doc.firstChild?.nodeSize ?? 0
                            if (slotPos !== null && slotPos < titleEnd) {
                                slotPos = null
                            }

                            setDragState(view, {
                                isDragging: true,
                                draggedPos,
                                slotPos,
                                slotGapIndex: slotPos === null ? null : gapIndex,
                            })

                            return false
                        },
                        dragleave(view, event) {
                            const related = event.relatedTarget as Node | null

                            if (related && view.dom.contains(related)) {
                                return false
                            }

                            setDragState(view, { slotPos: null, slotGapIndex: null })

                            return false
                        },
                        dragend(view) {
                            clearDragState(view)
                            return false
                        },
                    },
                },
            }),
        ]
    },
})
