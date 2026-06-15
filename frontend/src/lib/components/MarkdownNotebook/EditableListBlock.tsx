import {
    ClipboardEvent as ReactClipboardEvent,
    FormEvent,
    MutableRefObject,
    ReactNode,
    useCallback,
    useLayoutEffect,
    useMemo,
    useRef,
} from 'react'

import { getTaskItemShortcut, shouldUseMarkdownPaste } from './documentModel'
import { getInlineLinkPasteResult, getSelectionRange } from './domSelection'
import { RestoreSelectionRequest, TextSelectionPointerStartEvent } from './editorTypes'
import { splitInlineNodesAt } from './inlineContent'
import { RenderedListItem, buildRenderedListItems, getListItemIndex, getOrderedListStart } from './listModel'
import { htmlElementToInlineNodes, inlineNodesToHtml, parseMarkdownNotebook } from './markdown'
import { NotebookBlockNode, NotebookInlineNode, NotebookListBlockNode, NotebookListItem, NotebookMode } from './types'
import { getInlineText, normalizeInlineNodes } from './utils'

export function EditableListBlock({
    node,
    mode,
    setBlockRef,
    setListItemRef,
    updateNode,
    handleSelectionChange,
    startTextSelectionPointer,
    restoreSelectionRef,
}: {
    node: NotebookListBlockNode
    mode: NotebookMode
    setBlockRef: (element: HTMLElement | null) => void
    setListItemRef: (itemIndex: number, itemId: string | undefined, element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    handleSelectionChange: () => void
    startTextSelectionPointer: (event: TextSelectionPointerStartEvent) => void
    restoreSelectionRef: MutableRefObject<RestoreSelectionRequest | null>
}): JSX.Element {
    const renderedItems = useMemo(() => buildRenderedListItems(node.items), [node.items])
    const listBlockRef = useRef<HTMLDivElement | null>(null)

    const setListBlockRef = useCallback(
        (element: HTMLDivElement | null): void => {
            listBlockRef.current = element
            setBlockRef(element)
        },
        [setBlockRef]
    )

    const updateListItem = (
        itemIndex: number,
        itemId: string | undefined,
        updater: (item: NotebookListItem) => NotebookListItem
    ): void => {
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'list') {
                return currentNode
            }

            const targetItemIndex = getListItemIndex(currentNode.items, itemIndex, itemId)
            if (!currentNode.items[targetItemIndex]) {
                return currentNode
            }

            return {
                ...currentNode,
                items: currentNode.items.map((item, index) => (index === targetItemIndex ? updater(item) : item)),
            }
        })
    }

    const updateListItemChildren = (
        itemIndex: number,
        itemId: string | undefined,
        children: NotebookInlineNode[]
    ): void => {
        updateListItem(itemIndex, itemId, (item) => ({ ...item, children }))
    }

    const getListItemContentElement = (target: EventTarget | Node | null): HTMLElement | null => {
        const element = target instanceof Element ? target : target instanceof Node ? target.parentElement : null
        const itemElement = element?.closest('.MarkdownNotebook__list-item-content')
        if (!(itemElement instanceof HTMLElement) || !listBlockRef.current?.contains(itemElement)) {
            return null
        }

        return itemElement
    }

    const getActiveListItemContentElement = (): HTMLElement | null => {
        const selectionItemElement = getListItemContentElement(window.getSelection()?.anchorNode ?? null)
        if (selectionItemElement) {
            return selectionItemElement
        }

        return getListItemContentElement(document.activeElement)
    }

    const getListItemDetails = (
        element: HTMLElement
    ): { itemIndex: number; itemId: string | undefined; item: NotebookListItem } | null => {
        const itemIndex = Number(element.dataset.markdownNotebookListItemIndex)
        if (!Number.isInteger(itemIndex)) {
            return null
        }

        const itemId = element.dataset.markdownNotebookListItemId
        const targetItemIndex = getListItemIndex(node.items, itemIndex, itemId)
        const item = node.items[targetItemIndex]
        if (!item) {
            return null
        }

        return { itemIndex: targetItemIndex, itemId: item.id ?? itemId, item }
    }

    const updateListItemChildrenFromElement = (element: HTMLElement): void => {
        const details = getListItemDetails(element)
        if (!details) {
            return
        }

        updateListItemChildren(details.itemIndex, details.itemId, htmlElementToInlineNodes(element))
    }

    const handleListBlockInput = (event: FormEvent<HTMLDivElement>): void => {
        event.stopPropagation()
        if (event.target instanceof HTMLInputElement) {
            // Checkbox toggles go through onChange, not the contenteditable input flow
            return
        }
        const element = getListItemContentElement(event.target) ?? getActiveListItemContentElement()
        if (!element) {
            return
        }

        const details = getListItemDetails(element)
        if (!details) {
            return
        }

        const children = htmlElementToInlineNodes(element)
        const taskShortcut =
            details.item.checked === undefined && !(details.item.ordered ?? node.ordered)
                ? getTaskItemShortcut(children)
                : null
        if (taskShortcut) {
            const selection = getSelectionRange(element, node.id)
            const caretOffset = Math.max(0, (selection?.start ?? taskShortcut.markerLength) - taskShortcut.markerLength)
            updateListItem(details.itemIndex, details.itemId, (item) => ({
                ...item,
                checked: taskShortcut.checked,
                children: taskShortcut.children,
            }))
            restoreSelectionRef.current = {
                nodeId: node.id,
                listItemIndex: details.itemIndex,
                listItemId: details.itemId,
                start: caretOffset,
                end: caretOffset,
            }
            return
        }

        updateListItemChildren(details.itemIndex, details.itemId, children)
    }

    const handleListBlockPaste = (event: ReactClipboardEvent<HTMLDivElement>): void => {
        const element = getActiveListItemContentElement()
        const details = element ? getListItemDetails(element) : null
        if (!element || !details) {
            return
        }

        const plainText = event.clipboardData.getData('text/plain')
        const html = event.clipboardData.getData('text/html')
        const linkPasteResult = getInlineLinkPasteResult(element, node.id, details.item.children, plainText)
        if (linkPasteResult) {
            event.preventDefault()
            updateListItemChildren(details.itemIndex, details.itemId, linkPasteResult.children)
            restoreSelectionRef.current = {
                nodeId: node.id,
                listItemIndex: details.itemIndex,
                listItemId: details.itemId,
                start: linkPasteResult.start,
                end: linkPasteResult.end,
            }
            return
        }

        const pastedDocument = plainText ? parseMarkdownNotebook(plainText) : null
        if (
            pastedDocument &&
            pastedDocument.nodes.length === 1 &&
            pastedDocument.nodes[0].type === 'paragraph' &&
            shouldUseMarkdownPaste(plainText, html, pastedDocument)
        ) {
            event.preventDefault()
            const selection = getSelectionRange(element, node.id)
            const currentTextLength = getInlineText(details.item.children).length
            const selectionStart = selection ? Math.min(selection.start, selection.end) : currentTextLength
            const selectionEnd = selection ? Math.max(selection.start, selection.end) : currentTextLength
            const [beforeSelection, selectionAndAfter] = splitInlineNodesAt(details.item.children, selectionStart)
            const [, afterSelection] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)
            const nextChildren = normalizeInlineNodes([
                ...beforeSelection,
                ...pastedDocument.nodes[0].children,
                ...afterSelection,
            ])
            const nextCaretOffset =
                getInlineText(beforeSelection).length + getInlineText(pastedDocument.nodes[0].children).length
            updateListItemChildren(details.itemIndex, details.itemId, nextChildren)
            restoreSelectionRef.current = {
                nodeId: node.id,
                listItemIndex: details.itemIndex,
                listItemId: details.itemId,
                start: nextCaretOffset,
                end: nextCaretOffset,
            }
            return
        }

        if (!html) {
            return
        }

        event.preventDefault()
        const container = document.createElement('div')
        container.innerHTML = html
        document.execCommand('insertHTML', false, inlineNodesToHtml(htmlElementToInlineNodes(container)))
        updateListItemChildrenFromElement(element)
    }

    const toggleListItemChecked = (itemIndex: number, itemId: string | undefined): void => {
        updateListItem(itemIndex, itemId, (item) => ({ ...item, checked: !item.checked }))
    }

    const renderListItems = (items: RenderedListItem[], ordered: boolean): ReactNode =>
        items.map((item) => {
            const itemOrdered = item.ordered ?? ordered
            const isTaskItem = !itemOrdered && item.checked !== undefined
            return (
                <li
                    key={`${node.id}:${item.id ?? item.keyPath}`}
                    className={isTaskItem ? 'MarkdownNotebook__list-item--task' : undefined}
                >
                    {isTaskItem ? (
                        // The checkbox replaces the bullet; contentEditable={false} keeps the caret
                        // and text selection out of it inside the editable list block.
                        <span
                            className="MarkdownNotebook__task-checkbox"
                            contentEditable={false}
                            onMouseDown={(event) => event.stopPropagation()}
                            onPointerDown={(event) => event.stopPropagation()}
                        >
                            <input
                                type="checkbox"
                                checked={!!item.checked}
                                disabled={mode !== 'edit'}
                                onChange={() => toggleListItemChecked(item.index, item.id)}
                            />
                        </span>
                    ) : null}
                    <EditableListItemContent node={node} item={item} setListItemRef={setListItemRef} />
                    {item.childrenItems.length
                        ? renderItems(item.childrenItems, item.childrenItems[0].ordered ?? itemOrdered)
                        : null}
                </li>
            )
        })

    const renderItems = (items: RenderedListItem[], ordered: boolean, fallbackStart?: number): ReactNode => {
        if (ordered) {
            return <ol start={getOrderedListStart(items, ordered, fallbackStart)}>{renderListItems(items, ordered)}</ol>
        }

        return <ul>{renderListItems(items, ordered)}</ul>
    }

    return (
        <div
            className="MarkdownNotebook__list-block"
            ref={setListBlockRef}
            contentEditable={mode === 'edit'}
            suppressContentEditableWarning
            onInput={handleListBlockInput}
            onPaste={handleListBlockPaste}
            onMouseDown={startTextSelectionPointer}
            onPointerDown={startTextSelectionPointer}
            onTouchStart={startTextSelectionPointer}
            onMouseUp={handleSelectionChange}
            onKeyUp={handleSelectionChange}
        >
            {renderItems(renderedItems, node.ordered, node.start)}
        </div>
    )
}

export function EditableListItemContent({
    node,
    item,
    setListItemRef,
}: {
    node: NotebookListBlockNode
    item: RenderedListItem
    setListItemRef: (itemIndex: number, itemId: string | undefined, element: HTMLElement | null) => void
}): JSX.Element {
    const elementRef = useRef<HTMLDivElement | null>(null)
    const renderedHtml = useMemo(() => inlineNodesToHtml(item.children), [item.children])

    const setElementRef = useCallback(
        (element: HTMLDivElement | null): void => {
            elementRef.current = element
            setListItemRef(item.index, item.id, element)
        },
        [item.id, item.index, setListItemRef]
    )

    useLayoutEffect(() => {
        const element = elementRef.current
        if (!element) {
            return
        }

        if (element.innerHTML === renderedHtml) {
            return
        }

        // While the caret is inside the item, the DOM is the source of the latest model state:
        // rewriting innerHTML would destroy the caret mid-typing, so only sync when the live DOM
        // does not already represent the same content.
        const selection = window.getSelection()
        if (
            selection?.anchorNode &&
            element.contains(selection.anchorNode) &&
            inlineNodesToHtml(htmlElementToInlineNodes(element)) === renderedHtml
        ) {
            return
        }

        element.innerHTML = renderedHtml
    })

    return (
        <div
            ref={setElementRef}
            className="MarkdownNotebook__list-item-content"
            data-markdown-notebook-node-id={node.id}
            data-markdown-notebook-list-item-index={item.index}
            data-markdown-notebook-list-item-id={item.id}
            tabIndex={-1}
        />
    )
}
