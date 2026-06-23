import clsx from 'clsx'
import {
    ClipboardEvent as ReactClipboardEvent,
    FormEvent,
    KeyboardEvent,
    MutableRefObject,
    useCallback,
    useLayoutEffect,
    useMemo,
    useRef,
} from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import {
    getSlashCommandQuery,
    getTextBlockShortcutReplacement,
    getTitleChildrenFromMarkdownLine,
    getTitlePasteParts,
    isTextBlockNode,
    normalizeNotebookTitlePasteBodyNode,
    rekeyNotebookNodes,
    shouldUseMarkdownPaste,
} from './documentModel'
import {
    getCollapsedSelectionRange,
    getInlineLinkPasteResult,
    getSelectionRange,
    isSelectionAnchoredInsideElement,
    restoreSelection,
} from './domSelection'
import {
    InsertMenuSelectionDirection,
    InsertMenuState,
    RestoreSelectionRequest,
    TextSelectionPointerStartEvent,
} from './editorTypes'
import { splitInlineNodesAt } from './inlineContent'
import { htmlElementToInlineNodes, inlineNodesToHtml, makeEmptyParagraph, parseMarkdownNotebook } from './markdown'
import { NotebookBlockNode, NotebookInlineNode, NotebookMode, NotebookTextBlockNode } from './types'
import { getInlineText, normalizeInlineNodes } from './utils'

const AI_THINKING_LABEL = 'Thinking...'

export function EditableTextBlock({
    node,
    isTitleBlock,
    mode,
    placeholder,
    setBlockRef,
    updateNode,
    replaceNodeWithNodes,
    deleteSelectedNotebookBlocks,
    deleteNodeAndFocusPrevious,
    deleteNodeBefore,
    moveFocusToAdjacentNode,
    openInsertMenu,
    openDetachedInsertMenu,
    closeInsertMenu,
    moveInsertMenuSelection,
    toggleInsertMenu,
    activateInlineInsertMenuButton,
    showInlineInsertMenuButton,
    isInlineInsertMenuButtonVisible,
    isInsertMenuOpen,
    insertMenuMode,
    hasInvalidInsertMenuQuery,
    isAIWriting,
    isAIWritingPlaceholder,
    submitInsertMenuSelection,
    handleSelectionChange,
    startTextSelectionPointer,
    restoreSelectionRef,
    rootEditableInputHtmlByNodeIdRef,
}: {
    node: NotebookTextBlockNode
    isTitleBlock: boolean
    mode: NotebookMode
    placeholder: string | undefined
    setBlockRef: (element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    replaceNodeWithNodes: (nodeId: string, replacementNodes: NotebookBlockNode[]) => void
    deleteSelectedNotebookBlocks: () => boolean
    deleteNodeAndFocusPrevious: (nodeId: string) => boolean
    deleteNodeBefore: (nodeId: string, options?: { requireSameTextStyle?: boolean }) => boolean
    moveFocusToAdjacentNode: (nodeId: string, direction: InsertMenuSelectionDirection, offset: number) => boolean
    openInsertMenu: (query?: string) => void
    openDetachedInsertMenu: () => boolean
    closeInsertMenu: () => void
    moveInsertMenuSelection: (direction: InsertMenuSelectionDirection) => void
    toggleInsertMenu: () => void
    activateInlineInsertMenuButton: () => void
    showInlineInsertMenuButton: boolean
    isInlineInsertMenuButtonVisible: boolean
    isInsertMenuOpen: boolean
    insertMenuMode: InsertMenuState['mode'] | null
    hasInvalidInsertMenuQuery: boolean
    isAIWriting: boolean
    isAIWritingPlaceholder: boolean
    submitInsertMenuSelection: (queryOverride?: string) => boolean
    handleSelectionChange: () => void
    startTextSelectionPointer: (event: TextSelectionPointerStartEvent) => void
    restoreSelectionRef: MutableRefObject<RestoreSelectionRequest | null>
    rootEditableInputHtmlByNodeIdRef: MutableRefObject<Record<string, string>>
}): JSX.Element {
    const elementRef = useRef<HTMLElement | null>(null)
    const skipDomSyncForHtmlRef = useRef<string | null>(null)
    const renderedHtml = useMemo(() => inlineNodesToHtml(node.children), [node.children])
    const text = getInlineText(node.children)
    const isEmpty = text.length === 0
    const aiThinkingLabel = isAIWritingPlaceholder ? AI_THINKING_LABEL : undefined
    const isToolInsertMenuOpen = isInsertMenuOpen && (!insertMenuMode || insertMenuMode === 'tools')
    const TextTag =
        node.type === 'heading' ? (`h${node.level ?? 1}` as const) : node.type === 'blockquote' ? 'blockquote' : 'p'

    const setElementRef = useCallback(
        (element: HTMLElement | null): void => {
            elementRef.current = element
            setBlockRef(element)
        },
        [setBlockRef]
    )

    useLayoutEffect(() => {
        const element = elementRef.current
        if (!element) {
            return
        }

        const selection = window.getSelection()
        const rootEditableInputHtml = rootEditableInputHtmlByNodeIdRef.current[node.id]
        delete rootEditableInputHtmlByNodeIdRef.current[node.id]

        const shouldSkipOwnInputSync =
            (document.activeElement === element || isSelectionAnchoredInsideElement(selection, element)) &&
            (skipDomSyncForHtmlRef.current === renderedHtml || rootEditableInputHtml === renderedHtml)
        skipDomSyncForHtmlRef.current = null

        if (shouldSkipOwnInputSync || element.innerHTML === renderedHtml) {
            return
        }

        element.innerHTML = renderedHtml
    }, [renderedHtml, TextTag, node.id, rootEditableInputHtmlByNodeIdRef])

    const updateChildren = (nextChildren: NotebookInlineNode[]): NotebookInlineNode[] => {
        skipDomSyncForHtmlRef.current = inlineNodesToHtml(nextChildren)
        updateNode(node.id, (currentNode) => {
            if (!isTextBlockNode(currentNode)) {
                return currentNode
            }
            return {
                ...currentNode,
                children: nextChildren,
            }
        })
        return nextChildren
    }

    const updateElementAndChildren = (
        element: HTMLElement,
        nextChildren: NotebookInlineNode[]
    ): NotebookInlineNode[] => {
        const nextHtml = inlineNodesToHtml(nextChildren)
        if (element.innerHTML !== nextHtml) {
            element.innerHTML = nextHtml
        }
        restoreSelection(element, getInlineText(nextChildren).length, getInlineText(nextChildren).length)
        return updateChildren(nextChildren)
    }

    const updateFromElement = (element: HTMLElement): NotebookInlineNode[] =>
        updateChildren(htmlElementToInlineNodes(element))

    const replaceWithParagraph = (start = 0, end = start): void => {
        closeInsertMenu()
        updateNode(node.id, (currentNode) => {
            if (!isTextBlockNode(currentNode)) {
                return currentNode
            }

            return {
                ...currentNode,
                type: 'paragraph',
                level: undefined,
                children: currentNode.children,
            }
        })
        restoreSelectionRef.current = { nodeId: node.id, start, end }
    }

    const pasteMarkdownNodes = (
        element: HTMLElement,
        pastedNodes: NotebookBlockNode[],
        pastedMarkdown: string
    ): void => {
        const freshPastedNodes = rekeyNotebookNodes(pastedNodes, `paste-${node.id}-${pastedMarkdown.length}`)
        if (!freshPastedNodes.length) {
            return
        }

        const selection = getSelectionRange(element, node.id)
        const currentTextLength = getInlineText(node.children).length
        const selectionStart = selection ? Math.min(selection.start, selection.end) : currentTextLength
        const selectionEnd = selection ? Math.max(selection.start, selection.end) : currentTextLength
        const [beforeSelection, selectionAndAfter] = splitInlineNodesAt(node.children, selectionStart)
        const [, afterSelection] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)

        if (isTitleBlock) {
            const titlePaste = getTitlePasteParts(pastedMarkdown)
            const firstPastedNode = freshPastedNodes[0]
            const firstLineChildren: NotebookInlineNode[] = titlePaste.hasBodyMarkdown
                ? getTitleChildrenFromMarkdownLine(titlePaste.titleMarkdown)
                : firstPastedNode && isTextBlockNode(firstPastedNode)
                  ? firstPastedNode.children
                  : [{ type: 'text', text: titlePaste.titleMarkdown }]
            const nextTitleChildren = normalizeInlineNodes([
                ...beforeSelection,
                ...firstLineChildren,
                ...(titlePaste.hasBodyMarkdown ? [] : afterSelection),
            ])

            if (!titlePaste.hasBodyMarkdown) {
                updateNode(node.id, (currentNode) => {
                    if (!isTextBlockNode(currentNode)) {
                        return currentNode
                    }
                    return { ...currentNode, type: 'heading', level: 1, children: nextTitleChildren }
                })
                restoreSelectionRef.current = {
                    nodeId: node.id,
                    start: getInlineText(nextTitleChildren).length,
                    end: getInlineText(nextTitleChildren).length,
                }
                return
            }

            const bodyNodes = rekeyNotebookNodes(
                parseMarkdownNotebook(titlePaste.bodyMarkdown).nodes.map(normalizeNotebookTitlePasteBodyNode),
                `paste-title-body-${node.id}-${pastedMarkdown.length}`
            )
            const trailingParagraph =
                afterSelection.length || !bodyNodes.length
                    ? {
                          ...makeEmptyParagraph(`paste-title-after-${node.id}`),
                          children: afterSelection,
                      }
                    : null
            const replacementNodes = [
                { ...node, type: 'heading' as const, level: 1 as const, children: nextTitleChildren },
                ...bodyNodes,
                ...(trailingParagraph ? [trailingParagraph] : []),
            ]

            replaceNodeWithNodes(node.id, replacementNodes)

            const focusNode = trailingParagraph ?? [...bodyNodes].reverse().find(isTextBlockNode)
            if (focusNode && isTextBlockNode(focusNode)) {
                const caretOffset = getInlineText(focusNode.children).length
                restoreSelectionRef.current = { nodeId: focusNode.id, start: caretOffset, end: caretOffset }
            }
            return
        }

        const firstPastedNode = freshPastedNodes[0]

        if (
            freshPastedNodes.length === 1 &&
            firstPastedNode &&
            firstPastedNode.type === 'paragraph' &&
            (node.type === 'paragraph' || getInlineText(node.children).trim().length > 0)
        ) {
            const nextChildren = normalizeInlineNodes([
                ...beforeSelection,
                ...firstPastedNode.children,
                ...afterSelection,
            ])
            const nextCaretOffset =
                getInlineText(beforeSelection).length + getInlineText(firstPastedNode.children).length
            updateNode(node.id, (currentNode) => {
                if (!isTextBlockNode(currentNode)) {
                    return currentNode
                }
                return { ...currentNode, children: nextChildren }
            })
            restoreSelectionRef.current = { nodeId: node.id, start: nextCaretOffset, end: nextCaretOffset }
            return
        }

        const replacementNodes: NotebookBlockNode[] = []
        if (beforeSelection.length) {
            replacementNodes.push({ ...node, children: beforeSelection })
        }
        replacementNodes.push(...freshPastedNodes)

        const afterNode = afterSelection.length
            ? {
                  ...makeEmptyParagraph(`paste-after-${node.id}`),
                  children: afterSelection,
              }
            : null
        if (afterNode) {
            replacementNodes.push(afterNode)
        }

        replaceNodeWithNodes(node.id, replacementNodes)

        const focusNode = afterNode ?? [...freshPastedNodes].reverse().find(isTextBlockNode)
        if (focusNode && isTextBlockNode(focusNode)) {
            const caretOffset = afterNode ? 0 : getInlineText(focusNode.children).length
            restoreSelectionRef.current = { nodeId: focusNode.id, start: caretOffset, end: caretOffset }
            return
        }
    }

    const handleInput = (event: FormEvent<HTMLElement>): void => {
        if (isAIWriting) {
            event.currentTarget.innerHTML = renderedHtml
            return
        }

        const element = event.currentTarget
        const elementChildren = htmlElementToInlineNodes(element)
        const elementText = getInlineText(elementChildren)

        const shortcutReplacement = getTextBlockShortcutReplacement(node, isTitleBlock, elementText)
        if (shortcutReplacement) {
            closeInsertMenu()
            event.currentTarget.innerHTML = ''
            replaceNodeWithNodes(node.id, shortcutReplacement.nodes)
            restoreSelectionRef.current = shortcutReplacement.restoreSelection
            return
        }

        const slashQuery = getSlashCommandQuery(elementText)
        if (!isTitleBlock && slashQuery !== null) {
            const queryChildren: NotebookInlineNode[] = slashQuery ? [{ type: 'text', text: slashQuery }] : []
            openInsertMenu(slashQuery)
            updateElementAndChildren(element, queryChildren)
            return
        }

        const nextChildren = updateChildren(elementChildren)
        const nextText = getInlineText(nextChildren)
        if (isToolInsertMenuOpen) {
            openInsertMenu(nextText)
            return
        }

        closeInsertMenu()
    }

    const handlePaste = (event: ReactClipboardEvent<HTMLElement>): void => {
        if (isAIWriting) {
            event.preventDefault()
            return
        }

        const plainText = event.clipboardData.getData('text/plain')
        const html = event.clipboardData.getData('text/html')
        const linkPasteResult = getInlineLinkPasteResult(event.currentTarget, node.id, node.children, plainText)
        if (linkPasteResult) {
            event.preventDefault()
            updateElementAndChildren(event.currentTarget, linkPasteResult.children)
            restoreSelectionRef.current = {
                nodeId: node.id,
                start: linkPasteResult.start,
                end: linkPasteResult.end,
            }
            return
        }

        const pastedDocument = plainText ? parseMarkdownNotebook(plainText) : null
        if (pastedDocument && shouldUseMarkdownPaste(plainText, html, pastedDocument)) {
            event.preventDefault()
            pasteMarkdownNodes(event.currentTarget, pastedDocument.nodes, plainText)
            return
        }

        if (!html) {
            return
        }

        event.preventDefault()
        const container = document.createElement('div')
        container.innerHTML = html
        document.execCommand('insertHTML', false, inlineNodesToHtml(htmlElementToInlineNodes(container)))
        updateFromElement(event.currentTarget)
    }

    const handleBlur = (event: FormEvent<HTMLElement>): void => {
        const element = event.currentTarget
        const sanitizedHtml = inlineNodesToHtml(htmlElementToInlineNodes(element))
        if (element.innerHTML !== sanitizedHtml) {
            element.innerHTML = sanitizedHtml
        }
    }

    const handleKeyDown = (event: KeyboardEvent<HTMLElement>): void => {
        if (isAIWriting) {
            if (
                event.key.length === 1 ||
                event.key === 'Backspace' ||
                event.key === 'Delete' ||
                event.key === 'Enter'
            ) {
                event.preventDefault()
                event.stopPropagation()
            }
            return
        }

        if (isToolInsertMenuOpen && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'a') {
            event.preventDefault()
            event.stopPropagation()
            const textLength = getInlineText(node.children).length
            restoreSelection(event.currentTarget, 0, textLength)
            return
        }

        if (isToolInsertMenuOpen && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
            event.preventDefault()
            moveInsertMenuSelection(event.key === 'ArrowDown' ? 'next' : 'previous')
            return
        }

        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            const selection = getCollapsedSelectionRange(event.currentTarget, node.id)
            if (
                selection &&
                moveFocusToAdjacentNode(node.id, event.key === 'ArrowDown' ? 'next' : 'previous', selection.start)
            ) {
                event.preventDefault()
                return
            }
        }

        if (event.key === 'Enter' && !event.shiftKey) {
            const inputText = event.currentTarget.textContent ?? ''
            const slashQuery = getSlashCommandQuery(inputText)
            const insertMenuQuery = slashQuery ?? (isToolInsertMenuOpen ? inputText : undefined)

            if (submitInsertMenuSelection(insertMenuQuery)) {
                event.preventDefault()
                return
            }

            event.preventDefault()
            const selection = getCollapsedSelectionRange(event.currentTarget, node.id)
            const expandedSelection = getSelectionRange(event.currentTarget, node.id)
            const textLength = getInlineText(node.children).length
            const selectionStart = expandedSelection
                ? Math.max(0, Math.min(Math.min(expandedSelection.start, expandedSelection.end), textLength))
                : (selection?.start ?? textLength)
            const selectionEnd = expandedSelection
                ? Math.max(
                      selectionStart,
                      Math.min(Math.max(expandedSelection.start, expandedSelection.end), textLength)
                  )
                : selectionStart
            const [before, selectionAndAfter] = splitInlineNodesAt(node.children, selectionStart)
            const [, after] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)
            if (isTitleBlock) {
                const nextParagraph = makeEmptyParagraph(`after-title-${node.id}`)
                nextParagraph.children = after
                replaceNodeWithNodes(node.id, [{ ...node, type: 'heading', level: 1, children: before }, nextParagraph])
                restoreSelectionRef.current = { nodeId: nextParagraph.id, start: 0, end: 0 }
                return
            }

            if (node.type === 'heading') {
                if (selectionStart === 0) {
                    const previousParagraph = makeEmptyParagraph(`before-${node.id}`)
                    replaceNodeWithNodes(node.id, [previousParagraph, { ...node, children: after }])
                    restoreSelectionRef.current = { nodeId: previousParagraph.id, start: 0, end: 0 }
                    return
                }

                const nextHeadingId = makeEmptyParagraph(`after-${node.id}`).id
                replaceNodeWithNodes(node.id, [
                    { ...node, children: before },
                    {
                        ...node,
                        id: nextHeadingId,
                        children: after,
                    },
                ])
                restoreSelectionRef.current = { nodeId: nextHeadingId, start: 0, end: 0 }
                return
            }

            if (node.type === 'blockquote') {
                if (selectionStart === 0) {
                    const previousParagraph = makeEmptyParagraph(`before-${node.id}`)
                    replaceNodeWithNodes(node.id, [previousParagraph, { ...node, children: after }])
                    restoreSelectionRef.current = { nodeId: previousParagraph.id, start: 0, end: 0 }
                    return
                }

                const nextBlockquoteId = makeEmptyParagraph(`after-${node.id}`).id
                replaceNodeWithNodes(node.id, [
                    { ...node, children: before },
                    {
                        ...node,
                        id: nextBlockquoteId,
                        children: after,
                    },
                ])
                restoreSelectionRef.current = { nodeId: nextBlockquoteId, start: 0, end: 0 }
                return
            }

            const nextParagraph = makeEmptyParagraph(`after-${node.id}`)
            nextParagraph.children = after

            replaceNodeWithNodes(node.id, [{ ...node, children: before }, nextParagraph])
            restoreSelectionRef.current = { nodeId: nextParagraph.id, start: 0, end: 0 }
            return
        }

        if (event.key === 'Backspace' || event.key === 'Delete') {
            if (deleteSelectedNotebookBlocks()) {
                event.preventDefault()
                event.stopPropagation()
                return
            }

            const expandedSelection = getSelectionRange(event.currentTarget, node.id)
            if (expandedSelection && expandedSelection.start !== expandedSelection.end) {
                const textLength = getInlineText(node.children).length
                const selectionStart = Math.max(
                    0,
                    Math.min(Math.min(expandedSelection.start, expandedSelection.end), textLength)
                )
                const selectionEnd = Math.max(
                    selectionStart,
                    Math.min(Math.max(expandedSelection.start, expandedSelection.end), textLength)
                )
                const [beforeSelection, selectionAndAfter] = splitInlineNodesAt(node.children, selectionStart)
                const [, afterSelection] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)
                const nextChildren = normalizeInlineNodes([...beforeSelection, ...afterSelection])
                const nextHtml = inlineNodesToHtml(nextChildren)

                event.preventDefault()
                if (event.currentTarget.innerHTML !== nextHtml) {
                    event.currentTarget.innerHTML = nextHtml
                }
                restoreSelection(event.currentTarget, selectionStart, selectionStart)
                updateChildren(nextChildren)
                if (isToolInsertMenuOpen) {
                    openInsertMenu(getInlineText(nextChildren))
                }
                restoreSelectionRef.current = { nodeId: node.id, start: selectionStart, end: selectionStart }
                return
            }

            const selection = getCollapsedSelectionRange(event.currentTarget, node.id)
            if (isTitleBlock && event.key === 'Backspace' && selection?.start === 0 && selection.end === 0) {
                event.preventDefault()
                event.stopPropagation()
                restoreSelectionRef.current = { nodeId: node.id, start: 0, end: 0 }
                return
            }

            if (isEmpty && !isTitleBlock && node.type === 'paragraph' && event.key === 'Backspace') {
                event.preventDefault()
                if (!deleteNodeAndFocusPrevious(node.id)) {
                    updateNode(node.id, () => null)
                }
                return
            }

            if (
                !isTitleBlock &&
                event.key === 'Backspace' &&
                (node.type === 'heading' || node.type === 'blockquote') &&
                selection?.start === 0 &&
                selection.end === 0
            ) {
                event.preventDefault()
                if (deleteNodeBefore(node.id, { requireSameTextStyle: true })) {
                    return
                }
                replaceWithParagraph(0)
                return
            }

            if (
                event.key === 'Backspace' &&
                selection?.start === 0 &&
                selection.end === 0 &&
                deleteNodeBefore(node.id)
            ) {
                event.preventDefault()
                return
            }

            if (isEmpty && !isTitleBlock) {
                event.preventDefault()
                updateNode(node.id, () => null)
            }
        }
    }

    const focusEditableBlock = (): void => {
        const element = elementRef.current
        if (!element) {
            return
        }

        element.focus()
        const endOffset = getInlineText(htmlElementToInlineNodes(element)).length
        restoreSelection(element, endOffset, endOffset)
    }

    const handleInsertMenuButtonClick = (): void => {
        const isInsideTextGroup = elementRef.current?.closest('.MarkdownNotebook__text-group') instanceof HTMLElement
        const shouldDetachInsertMenu = isInsideTextGroup && !isToolInsertMenuOpen

        if (isToolInsertMenuOpen) {
            const caretOffset = getInlineText(node.children).length
            restoreSelectionRef.current = { nodeId: node.id, start: caretOffset, end: caretOffset }
            toggleInsertMenu()
            return
        }

        if (shouldDetachInsertMenu && openDetachedInsertMenu()) {
            return
        }

        toggleInsertMenu()
        focusEditableBlock()
    }

    return (
        <div
            className={clsx(
                'MarkdownNotebook__text-row',
                showInlineInsertMenuButton &&
                    isInlineInsertMenuButtonVisible &&
                    'MarkdownNotebook__text-row--inline-menu-visible'
            )}
        >
            {showInlineInsertMenuButton ? (
                <span
                    className="MarkdownNotebook__line-insert-menu-hit-area"
                    contentEditable={false}
                    onMouseEnter={activateInlineInsertMenuButton}
                    onMouseMove={activateInlineInsertMenuButton}
                >
                    <LemonButton
                        size="xsmall"
                        icon={
                            <span className="MarkdownNotebook__line-insert-menu-icon">
                                {isToolInsertMenuOpen ? <IconX /> : '+'}
                            </span>
                        }
                        className="MarkdownNotebook__line-insert-menu-button"
                        active={isToolInsertMenuOpen}
                        tooltip={isToolInsertMenuOpen ? 'Close menu' : 'Add block'}
                        onClick={handleInsertMenuButtonClick}
                        aria-label={isInsertMenuOpen ? 'Close add block menu' : 'Open add block menu'}
                        aria-expanded={isInsertMenuOpen}
                        tabIndex={isInlineInsertMenuButtonVisible ? 0 : -1}
                    />
                </span>
            ) : null}
            <TextTag
                ref={setElementRef}
                className={clsx(
                    'MarkdownNotebook__text-block',
                    `MarkdownNotebook__text-block--${node.type}`,
                    isTitleBlock && 'MarkdownNotebook__text-block--title',
                    isToolInsertMenuOpen && 'MarkdownNotebook__text-block--insert-placeholder',
                    isAIWriting && 'MarkdownNotebook__text-block--ai-writing',
                    isAIWritingPlaceholder && 'MarkdownNotebook__text-block--ai-thinking',
                    hasInvalidInsertMenuQuery && 'MarkdownNotebook__text-block--invalid-insert-filter'
                )}
                data-markdown-notebook-node-id={node.id}
                data-ai-thinking-label={aiThinkingLabel}
                contentEditable={mode === 'edit' && !isAIWriting}
                suppressContentEditableWarning
                aria-busy={isAIWriting || undefined}
                data-placeholder={isEmpty ? placeholder : undefined}
                onInput={handleInput}
                onPaste={handlePaste}
                onBlur={handleBlur}
                onKeyDown={handleKeyDown}
                onMouseDown={startTextSelectionPointer}
                onPointerDown={startTextSelectionPointer}
                onTouchStart={startTextSelectionPointer}
                onMouseUp={handleSelectionChange}
                onKeyUp={handleSelectionChange}
            />
        </div>
    )
}
