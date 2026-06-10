import './MarkdownNotebook.scss'

import clsx from 'clsx'
import {
    ChangeEvent as ReactChangeEvent,
    ClipboardEvent as ReactClipboardEvent,
    FocusEvent as ReactFocusEvent,
    FormEvent,
    Fragment,
    KeyboardEvent,
    MouseEvent as ReactMouseEvent,
    useCallback,
    useEffect,
    useId,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from 'react'

import { IconCode } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { mergeNotebookMarkdownChanges } from './collaboration'
import {
    ComponentPanelCacheEntry,
    ComponentPanelVisibility,
    DEFAULT_COMPONENT_PANEL_VISIBILITY,
    INSERTED_COMPONENT_PANEL_VISIBILITY,
    getComponentPanelVisibility,
    shouldPersistComponentPanelProps,
    withPersistedComponentPanelProps,
} from './componentPanels'
import {
    areNotebookDocumentsEqual,
    ensureEditableNotebookDocument,
    getAskAISelectionQuery,
    getClipboardMarkdown,
    getHistoryRestoreSelection,
    getInlineInsertMenuQuery,
    getMarkdownNotebookVisualGroups,
    getNotebookStringProp,
    getPromptSource,
    getSlashCommandQuery,
    getTextBlockShortcutReplacement,
    hasNotebookContent,
    isBlankInsertMenuButtonRow,
    isPromptComponentNode,
    isTextBlockNode,
    makeEmptyNotebookTitle,
    readSystemClipboardText,
    rekeyNotebookNodes,
    serializeNotebookNodes,
    setClipboardMarkdown,
    setsEqual,
    textBlocksShareContinuationStyle,
    writeSystemClipboardText,
} from './documentModel'
import {
    findTextPosition,
    getCollapsedSelectionRange,
    getCollapsedSelectionRestoreRequest,
    getComponentNodeForSelection,
    getElementLineHeight,
    getFocusedComponentNode,
    getInlineEditableElementForSelection,
    getNormalizedSelectionBounds,
    getNotebookBlockElement,
    getSelectedCodeRanges,
    getSelectedComponentNodeIds,
    getSelectedInlineEditableElementOfType,
    getSelectedListItemRanges,
    getSelectedNotebookMarkdown,
    getSelectedTextRanges,
    getSelectionClientRect,
    getSelectionRange,
    isFormattingToolbarFocused,
    isNativeEditableElement,
    isSelectionInsideElement,
    rangeIntersectsNode,
    restoreSelection,
    restoreTextSelectionRanges,
    scrollNotebookElementIntoView,
    selectionMatchesRange,
    setNotebookSelectionEnd,
    setNotebookSelectionStart,
} from './domSelection'
import {
    FLOATING_TOOLBAR_ESTIMATED_HEIGHT,
    FLOATING_TOOLBAR_GAP,
    FLOATING_TOOLBAR_REVEAL_DELAY_MS,
    FloatingToolbarListItemRange,
    FloatingToolbarPointerAnchor,
    FloatingToolbarPosition,
    FloatingToolbarState,
    FloatingToolbarTextRange,
    INSERT_MENU_PLACEHOLDER,
    InsertMenuPosition,
    InsertMenuSelectionDirection,
    InsertMenuState,
    MAX_UNDO_HISTORY_ENTRIES,
    NOTEBOOK_TITLE_PLACEHOLDER,
    RestoreSelectionRequest,
    RestoreTextRange,
    TableCellPosition,
    TextBlockStyle,
    TextSelectionPointerStartEvent,
    TextSelectionPointerState,
} from './editorTypes'
import { FormattingToolbar, getFloatingToolbarLinkHref, getSelectedBlockStyle } from './FormattingToolbar'
import {
    InlineMarkSelection,
    areInlineSelectionsFullyMarked,
    plainTextToInlineNodes,
    setInlineLinkMark,
    setInlineMark,
    splitInlineNodesAt,
} from './inlineContent'
import {
    InsertBoundaryButton,
    getClosestInsertBoundaryIndex,
    isInsertBoundaryAvailable,
    isInsertBoundaryVisible,
} from './InsertBoundaryButton'
import {
    InsertMenu,
    buildInsertCommands,
    getClampedInsertMenuSelectedIndex,
    getFilteredInsertCommands,
    getInsertMenuPosition,
    getNextInsertMenuSelectedIndex,
} from './InsertMenu'
import {
    getListItemIndex,
    getListItemParagraphReplacement,
    getListItemRefKey,
    shiftListItemSubtreeDepth,
} from './listModel'
import {
    htmlElementToInlineNodes,
    inlineNodesToHtml,
    makeEmptyParagraph,
    makeListItemId,
    parseMarkdownNotebook,
    serializeMarkdownNotebook,
} from './markdown'
import { reconcileNotebookDocuments } from './reconcile'
import {
    getMarkdownNotebookComponentDefinition,
    getMarkdownNotebookDefaultRegistry,
    mergeMarkdownNotebookRegistries,
} from './registry'
import { renderNode } from './renderNode'
import {
    getTableCellAtPosition,
    getTableCellPositionFromElement,
    getTableCellPositions,
    getTableCellRefKey,
    getTableColumnCount,
    getTableEdgeCellPosition,
    makeEmptyTableRow,
    normalizeTableRow,
    tableCellPositionsEqual,
} from './tableModel'
import {
    NotebookBlockNode,
    NotebookCollaborationConflict,
    NotebookComponentBlockNode,
    NotebookComponentProps,
    NotebookComponentRegistry,
    NotebookDocument,
    NotebookInlineMark,
    NotebookInlineNode,
    NotebookListItem,
    NotebookMode,
    NotebookTableBlockNode,
    NotebookTextBlockNode,
    NotebookTextSelectionRange,
} from './types'
import { cloneNotebookDocument, cloneNotebookNode, getInlineText, normalizeInlineNodes } from './utils'

export type MarkdownNotebookProps = {
    value: string
    onChange?: (value: string) => void
    onAskAI?: (request: MarkdownNotebookAskAIRequest) => void
    createAIChatId?: () => string
    mode?: NotebookMode
    registry?: NotebookComponentRegistry
    remoteValue?: string
    deferRemoteValue?: boolean
    clientId?: string
    onConflict?: (conflicts: NotebookCollaborationConflict[]) => void
    onInteractionStateChange?: (isInteractionActive: boolean) => void
    initialInsertMenu?: { nodeIndex?: number; query?: string }
    placeholder?: string
    className?: string
    autoFocus?: boolean
    showDebug?: boolean
    'data-attr'?: string
}

export type MarkdownNotebookAskAIRequest = {
    chatId: string
    query: string
    source: 'slash' | 'selection'
    chatNodeId: string
    chatMarker: string
    markdown: string
    markdownWithChat: string
    selectedMarkdown?: string
}

type DebugTextareaSelection = {
    start: number
    end: number
    direction: 'forward' | 'backward' | 'none'
}

type CommitDocumentOptions = {
    addToHistory?: boolean
}

type NotebookHistoryState = {
    undo: NotebookDocument[]
    redo: NotebookDocument[]
}

function createDefaultAIChatId(): string {
    if (typeof window !== 'undefined' && window.crypto?.randomUUID) {
        return window.crypto.randomUUID()
    }
    return makeEmptyParagraph('ai-chat').id
}

export function MarkdownNotebook({
    value,
    onChange,
    onAskAI,
    createAIChatId = createDefaultAIChatId,
    mode = 'edit',
    registry,
    remoteValue,
    deferRemoteValue = false,
    onConflict,
    onInteractionStateChange,
    initialInsertMenu,
    placeholder = 'Start writing...',
    className,
    autoFocus = false,
    showDebug = false,
    'data-attr': dataAttr = 'markdown-notebook',
}: MarkdownNotebookProps): JSX.Element {
    const mergedRegistry = useMemo(
        () => mergeMarkdownNotebookRegistries(getMarkdownNotebookDefaultRegistry(), registry),
        [registry]
    )
    const [document, setDocument] = useState<NotebookDocument>(() =>
        ensureEditableNotebookDocument(parseMarkdownNotebook(value))
    )
    const [floatingToolbar, setFloatingToolbar] = useState<FloatingToolbarState | null>(null)
    const [insertMenu, setInsertMenu] = useState<InsertMenuState | null>(null)
    const [insertMenuPosition, setInsertMenuPosition] = useState<InsertMenuPosition | null>(null)
    const [activeRowIndex, setActiveRowIndex] = useState<number | null>(null)
    const [activeBoundaryIndex, setActiveBoundaryIndex] = useState<number | null>(null)
    const [focusedRowIndex, setFocusedRowIndex] = useState<number | null>(null)
    const [selectedComponentNodeIds, setSelectedComponentNodeIds] = useState<Set<string>>(() => new Set())
    const [componentPanelCache, setComponentPanelCache] = useState<Record<string, ComponentPanelCacheEntry>>({})
    const [isDebugOpen, setIsDebugOpen] = useState(false)
    const [debugMarkdown, setDebugMarkdown] = useState(() => serializeMarkdownNotebook(document))
    const debugDrawerId = useId()
    const debugTextareaRef = useRef<HTMLTextAreaElement | null>(null)
    const pendingDebugSelectionRef = useRef<DebugTextareaSelection | null>(null)
    const notebookRef = useRef<HTMLDivElement | null>(null)
    const canvasRef = useRef<HTMLDivElement | null>(null)
    const documentRef = useRef(document)
    const blockRefs = useRef<Record<string, HTMLElement | null>>({})
    const listItemRefs = useRef<Record<string, HTMLElement | null>>({})
    const tableCellRefs = useRef<Record<string, HTMLElement | null>>({})
    const rootEditableInputHtmlByNodeIdRef = useRef<Record<string, string>>({})
    const isTextSelectionPointerActiveRef = useRef(false)
    const floatingToolbarRevealTimeoutRef = useRef<number | null>(null)
    const floatingToolbarRevealAfterRef = useRef(0)
    const textSelectionPointerStateRef = useRef<TextSelectionPointerState | null>(null)
    const floatingToolbarPointerAnchorRef = useRef<FloatingToolbarPointerAnchor | null>(null)
    const floatingToolbarPositionLockRef = useRef<FloatingToolbarPosition | null>(null)
    const focusNodeRef = useRef<string | null>(null)
    const restoreSelectionRef = useRef<RestoreSelectionRequest | null>(null)
    const notebookClipboardMarkdownRef = useRef<string | null>(null)
    const historyRef = useRef<NotebookHistoryState>({ undo: [], redo: [] })
    const lastSerializedValueRef = useRef(value)
    // The three-way merge base: the last server state local edits were derived from.
    const lastBaseValueRef = useRef(remoteValue ?? value)
    const lastRemoteValueRef = useRef(remoteValue)
    const pendingRemoteValueRef = useRef<string | null>(null)
    const initialInsertMenuAppliedRef = useRef(false)
    const emptyNodeRef = useRef<NotebookTextBlockNode>(makeEmptyParagraph('initial-empty'))
    const initializedComponentPanelNodeIdsRef = useRef<Set<string> | null>(null)

    const setLocalComponentPanels = useCallback((nodeId: string, panels: ComponentPanelVisibility): void => {
        setComponentPanelCache((currentCache) => ({
            ...currentCache,
            [nodeId]: {
                ...currentCache[nodeId],
                current: panels,
            },
        }))
    }, [])

    const rememberComponentPanels = useCallback((nodeId: string, panels: ComponentPanelVisibility): void => {
        setComponentPanelCache((currentCache) => ({
            ...currentCache,
            [nodeId]: {
                ...currentCache[nodeId],
                remembered: panels,
            },
        }))
    }, [])

    const clearFloatingToolbarRevealTimeout = useCallback((): void => {
        if (floatingToolbarRevealTimeoutRef.current === null) {
            return
        }

        window.clearTimeout(floatingToolbarRevealTimeoutRef.current)
        floatingToolbarRevealTimeoutRef.current = null
    }, [])

    useEffect(() => {
        if (!showDebug) {
            setIsDebugOpen(false)
        }
    }, [showDebug])

    useEffect(() => {
        if (value === lastSerializedValueRef.current) {
            return
        }

        const restoreSelectionRequest = notebookRef.current
            ? getCollapsedSelectionRestoreRequest(window.getSelection(), notebookRef.current)
            : null
        setDocument((currentDocument) => {
            const nextDocument = parseMarkdownNotebook(value)
            const reconciledDocument = ensureEditableNotebookDocument(
                reconcileNotebookDocuments(currentDocument, nextDocument).document
            )
            documentRef.current = reconciledDocument
            return reconciledDocument
        })
        if (restoreSelectionRequest) {
            restoreSelectionRef.current = restoreSelectionRequest
        }
        setDebugMarkdown(value)
        historyRef.current = { undo: [], redo: [] }
        // The base is intentionally left untouched: an external `value` change is a local-side
        // update (artifact apply, restore), so the last synced server state remains the merge base.
        lastSerializedValueRef.current = value
    }, [value])

    useLayoutEffect(() => {
        const debugSelection = pendingDebugSelectionRef.current
        const debugTextarea = debugTextareaRef.current
        if (debugSelection) {
            pendingDebugSelectionRef.current = null
            if (debugTextarea && window.document.activeElement === debugTextarea) {
                const selectionStart = Math.min(debugSelection.start, debugTextarea.value.length)
                const selectionEnd = Math.min(debugSelection.end, debugTextarea.value.length)
                debugTextarea.setSelectionRange(selectionStart, selectionEnd, debugSelection.direction)
                return
            }
        }

        const request = restoreSelectionRef.current
        if (request) {
            restoreSelectionRef.current = null
            if ('textRanges' in request) {
                restoreTextSelectionRanges(request.textRanges, blockRefs.current, listItemRefs.current)
                return
            }

            const listItemRefKey =
                request.listItemId ?? (request.listItemIndex === undefined ? undefined : String(request.listItemIndex))
            const element =
                request.tableCell !== undefined
                    ? tableCellRefs.current[getTableCellRefKey(request.nodeId, request.tableCell)]
                    : listItemRefKey === undefined
                      ? (blockRefs.current[request.nodeId] ??
                        getNotebookBlockElement(notebookRef.current, request.nodeId))
                      : (listItemRefs.current[getListItemRefKey(request.nodeId, listItemRefKey)] ??
                        (request.listItemIndex === undefined
                            ? undefined
                            : listItemRefs.current[getListItemRefKey(request.nodeId, request.listItemIndex)]))
            if (element) {
                element.focus()
                restoreSelection(element, request.start, request.end)
                scrollNotebookElementIntoView(element)
            }
            return
        }

        const focusNodeId = focusNodeRef.current
        if (focusNodeId) {
            focusNodeRef.current = null
            const element = blockRefs.current[focusNodeId]
            element?.focus()
            if (element) {
                scrollNotebookElementIntoView(element)
            }
        }
    }, [debugMarkdown, document])

    useEffect(() => {
        if (!autoFocus || mode !== 'edit') {
            return
        }

        const firstTextNode = getRenderedNodes()[0]
        const firstElement = firstTextNode ? blockRefs.current[firstTextNode.id] : null
        firstElement?.focus()
        // oxlint-disable-next-line exhaustive-deps
    }, [autoFocus, mode])

    useEffect(() => {
        if (!initialInsertMenu || initialInsertMenuAppliedRef.current || mode !== 'edit') {
            return
        }

        const nodes = getRenderedNodes()
        const node = nodes[initialInsertMenu.nodeIndex ?? 0]
        if (node) {
            initialInsertMenuAppliedRef.current = true
            setInsertMenu({ nodeId: node.id, query: initialInsertMenu.query ?? '', selectedIndex: 0, mode: 'tools' })
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [initialInsertMenu, mode])

    const commitDocument = useCallback(
        (nextDocument: NotebookDocument, options: CommitDocumentOptions = {}): void => {
            const editableDocument = ensureEditableNotebookDocument(nextDocument)
            const previousDocument = documentRef.current
            if ((options.addToHistory ?? true) && !areNotebookDocumentsEqual(previousDocument, editableDocument)) {
                historyRef.current = {
                    undo: [
                        ...historyRef.current.undo.slice(-(MAX_UNDO_HISTORY_ENTRIES - 1)),
                        cloneNotebookDocument(previousDocument),
                    ],
                    redo: [],
                }
            }

            const serialized = serializeMarkdownNotebook(editableDocument)
            documentRef.current = editableDocument
            lastSerializedValueRef.current = serialized
            setDebugMarkdown(serialized)
            setDocument(editableDocument)
            onChange?.(serialized)
        },
        [onChange]
    )

    const applyRemoteValue = useCallback(
        (nextRemoteValue: string): void => {
            if (nextRemoteValue === lastSerializedValueRef.current) {
                // The remote state caught up with local edits (autosave echo): fully synced,
                // nothing changes locally — undo history must survive autosaves.
                lastRemoteValueRef.current = nextRemoteValue
                lastBaseValueRef.current = nextRemoteValue
                return
            }

            const mergeResult = mergeNotebookMarkdownChanges({
                baseMarkdown: lastBaseValueRef.current,
                localMarkdown: lastSerializedValueRef.current,
                remoteMarkdown: nextRemoteValue,
            })
            const reconciledDocument = reconcileNotebookDocuments(documentRef.current, mergeResult.document).document
            const restoreSelectionRequest = notebookRef.current
                ? getCollapsedSelectionRestoreRequest(window.getSelection(), notebookRef.current)
                : null
            lastRemoteValueRef.current = nextRemoteValue
            // The merge result still contains unsaved local changes, so the server state — not the
            // merge result — is the common ancestor for the next merge.
            lastBaseValueRef.current = nextRemoteValue
            historyRef.current = { undo: [], redo: [] }
            if (restoreSelectionRequest) {
                restoreSelectionRef.current = restoreSelectionRequest
            }
            commitDocument(reconciledDocument, { addToHistory: false })

            if (mergeResult.conflicts.length) {
                onConflict?.(mergeResult.conflicts)
            }
        },
        [commitDocument, onConflict]
    )

    useEffect(() => {
        const nextRemoteValue = pendingRemoteValueRef.current ?? remoteValue
        if (
            nextRemoteValue === null ||
            nextRemoteValue === undefined ||
            nextRemoteValue === lastRemoteValueRef.current
        ) {
            return
        }

        if (deferRemoteValue) {
            pendingRemoteValueRef.current = nextRemoteValue
            return
        }

        pendingRemoteValueRef.current = null
        applyRemoteValue(nextRemoteValue)
    }, [remoteValue, deferRemoteValue, applyRemoteValue])

    const isInsertMenuInteractionActive = !!insertMenu
    const isTransientInteractionActive = mode === 'edit' && (isInsertMenuInteractionActive || !!floatingToolbar)

    useEffect(() => {
        onInteractionStateChange?.(isTransientInteractionActive)
        return () => {
            if (isTransientInteractionActive) {
                onInteractionStateChange?.(false)
            }
        }
    }, [isTransientInteractionActive, onInteractionStateChange])

    const restoreHistoryDocument = useCallback(
        (targetDocument: NotebookDocument): void => {
            const editableDocument = ensureEditableNotebookDocument(cloneNotebookDocument(targetDocument))
            restoreSelectionRef.current = getHistoryRestoreSelection(editableDocument)
            commitDocument(editableDocument, { addToHistory: false })
        },
        [commitDocument]
    )

    const undoHistory = useCallback((): boolean => {
        const previousDocument = historyRef.current.undo[historyRef.current.undo.length - 1]
        if (!previousDocument) {
            return false
        }

        historyRef.current = {
            undo: historyRef.current.undo.slice(0, -1),
            redo: [
                ...historyRef.current.redo.slice(-(MAX_UNDO_HISTORY_ENTRIES - 1)),
                cloneNotebookDocument(documentRef.current),
            ],
        }
        restoreHistoryDocument(previousDocument)
        return true
    }, [restoreHistoryDocument])

    const redoHistory = useCallback((): boolean => {
        const nextDocument = historyRef.current.redo[historyRef.current.redo.length - 1]
        if (!nextDocument) {
            return false
        }

        historyRef.current = {
            undo: [
                ...historyRef.current.undo.slice(-(MAX_UNDO_HISTORY_ENTRIES - 1)),
                cloneNotebookDocument(documentRef.current),
            ],
            redo: historyRef.current.redo.slice(0, -1),
        }
        restoreHistoryDocument(nextDocument)
        return true
    }, [restoreHistoryDocument])

    const deleteSelectedNotebookBlocks = useCallback(
        (replacementText: string = ''): boolean => {
            const notebookElement = notebookRef.current
            const selection = window.getSelection()
            if (!notebookElement || !selection || selection.rangeCount === 0 || selection.isCollapsed) {
                return false
            }

            const range = selection.getRangeAt(0)
            if (!rangeIntersectsNode(range, notebookElement)) {
                return false
            }

            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const selectedEntries = nodes
                .map((node, index) => ({ node, index, element: blockRefs.current[node.id] }))
                .filter(
                    (entry): entry is { node: NotebookBlockNode; index: number; element: HTMLElement } =>
                        !!entry.element && rangeIntersectsNode(range, entry.element)
                )

            if (selectedEntries.length <= 1) {
                return false
            }

            const requestFocusForDeletedSelection = (
                nextNodes: NotebookBlockNode[],
                selectionStartIndex: number
            ): void => {
                const requestFocusForNode = (node: NotebookBlockNode, placement: 'start' | 'end'): boolean => {
                    const offsetForChildren = (children: NotebookInlineNode[]): number =>
                        placement === 'start' ? 0 : getInlineText(children).length

                    if (isTextBlockNode(node)) {
                        const offset = offsetForChildren(node.children)
                        restoreSelectionRef.current = { nodeId: node.id, start: offset, end: offset }
                        return true
                    }

                    if (node.type === 'component') {
                        focusNodeRef.current = node.id
                        return true
                    }

                    if (node.type === 'list' && node.items.length) {
                        const listItemIndex = placement === 'start' ? 0 : node.items.length - 1
                        const offset = offsetForChildren(node.items[listItemIndex].children)
                        restoreSelectionRef.current = {
                            nodeId: node.id,
                            listItemIndex,
                            listItemId: node.items[listItemIndex].id,
                            start: offset,
                            end: offset,
                        }
                        return true
                    }

                    if (node.type === 'table') {
                        const tableCell = getTableEdgeCellPosition(node, placement === 'start' ? 'next' : 'previous')
                        if (!tableCell) {
                            return false
                        }

                        const offset = offsetForChildren(getTableCellAtPosition(node, tableCell)?.children ?? [])
                        restoreSelectionRef.current = { nodeId: node.id, tableCell, start: offset, end: offset }
                        return true
                    }

                    return false
                }

                for (const node of nextNodes.slice(selectionStartIndex)) {
                    if (requestFocusForNode(node, 'start')) {
                        return
                    }
                }

                for (const node of nextNodes.slice(0, selectionStartIndex).reverse()) {
                    if (requestFocusForNode(node, 'end')) {
                        return
                    }
                }
            }

            const firstEntry = selectedEntries[0]
            const lastEntry = selectedEntries[selectedEntries.length - 1]
            const selectedIndexes = new Set(selectedEntries.map((entry) => entry.index))
            let replacementNode: NotebookTextBlockNode | null = null
            let restoreOffset = 0
            const insertedChildren: NotebookInlineNode[] = replacementText
                ? [{ type: 'text', text: replacementText }]
                : []
            const insertedTextLength = getInlineText(insertedChildren).length

            if (isTextBlockNode(firstEntry.node)) {
                const firstBounds = getNormalizedSelectionBounds(firstEntry.node, firstEntry.element)
                const [beforeSelection] = splitInlineNodesAt(firstEntry.node.children, firstBounds.start)
                const beforeTextLength = getInlineText(beforeSelection).length

                if (isTextBlockNode(lastEntry.node)) {
                    const lastBounds = getNormalizedSelectionBounds(lastEntry.node, lastEntry.element)
                    const [, afterSelection] = splitInlineNodesAt(lastEntry.node.children, lastBounds.end)
                    const hasRemainingText =
                        firstBounds.start > 0 || insertedTextLength > 0 || lastBounds.end < lastBounds.textLength

                    if (hasRemainingText || firstEntry.index === 0) {
                        replacementNode = {
                            ...firstEntry.node,
                            children: normalizeInlineNodes([
                                ...beforeSelection,
                                ...insertedChildren,
                                ...afterSelection,
                            ]),
                        }
                        restoreOffset = beforeTextLength + insertedTextLength
                    }
                } else if (firstBounds.start > 0 || insertedTextLength > 0 || firstEntry.index === 0) {
                    replacementNode = {
                        ...firstEntry.node,
                        children: normalizeInlineNodes([...beforeSelection, ...insertedChildren]),
                    }
                    restoreOffset = beforeTextLength + insertedTextLength
                }
            } else if (isTextBlockNode(lastEntry.node)) {
                const lastBounds = getNormalizedSelectionBounds(lastEntry.node, lastEntry.element)
                const [, afterSelection] = splitInlineNodesAt(lastEntry.node.children, lastBounds.end)
                if (insertedTextLength > 0 || lastBounds.end < lastBounds.textLength) {
                    replacementNode = {
                        ...lastEntry.node,
                        children: normalizeInlineNodes([...insertedChildren, ...afterSelection]),
                    }
                    restoreOffset = insertedTextLength
                }
            }

            if (!replacementNode && firstEntry.index === 0) {
                replacementNode = makeEmptyNotebookTitle(`delete-selection-${firstEntry.node.id}`)
                if (insertedChildren.length) {
                    replacementNode.children = insertedChildren
                    restoreOffset = insertedTextLength
                }
            } else if (!replacementNode && insertedChildren.length) {
                replacementNode = makeEmptyParagraph(`replace-selection-${firstEntry.node.id}`)
                replacementNode.children = insertedChildren
                restoreOffset = insertedTextLength
            }

            const replacementNodes = replacementNode ? [replacementNode] : []
            const nextNodes = nodes.flatMap((node, index) => {
                if (index === firstEntry.index) {
                    return replacementNodes
                }
                return selectedIndexes.has(index) ? [] : [node]
            })

            if (replacementNode) {
                restoreSelectionRef.current = {
                    nodeId: replacementNode.id,
                    start: restoreOffset,
                    end: restoreOffset,
                }
            } else {
                requestFocusForDeletedSelection(nextNodes, firstEntry.index)
            }

            selection.removeAllRanges()
            setSelectedComponentNodeIds(new Set())
            floatingToolbarPositionLockRef.current = null
            setFloatingToolbar(null)
            commitDocument({
                ...currentDocument,
                nodes: nextNodes,
            })
            return true
        },
        [commitDocument]
    )

    const splitTextBlockAtCurrentSelection = useCallback((): boolean => {
        const notebookElement = notebookRef.current
        if (!notebookElement) {
            return false
        }

        const selection = window.getSelection()
        const inlineEditableElement = getInlineEditableElementForSelection(selection, notebookElement)
        if (!inlineEditableElement?.classList.contains('MarkdownNotebook__text-block')) {
            return false
        }

        const nodeId = inlineEditableElement.dataset.markdownNotebookNodeId
        if (!nodeId || insertMenu?.nodeId === nodeId) {
            return false
        }

        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
        const nodeIndex = nodes.findIndex((node) => node.id === nodeId)
        const node = nodes[nodeIndex]
        if (!node || !isTextBlockNode(node)) {
            return false
        }

        const expandedSelection = getSelectionRange(inlineEditableElement, node.id)
        const textLength = getInlineText(node.children).length
        const selectionStart = expandedSelection
            ? Math.max(0, Math.min(Math.min(expandedSelection.start, expandedSelection.end), textLength))
            : textLength
        const selectionEnd = expandedSelection
            ? Math.max(selectionStart, Math.min(Math.max(expandedSelection.start, expandedSelection.end), textLength))
            : selectionStart
        const [before, selectionAndAfter] = splitInlineNodesAt(node.children, selectionStart)
        const [, after] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)
        let replacementNodes: NotebookBlockNode[]

        if (nodeIndex === 0) {
            const nextParagraph = makeEmptyParagraph(`after-title-${node.id}`)
            nextParagraph.children = after
            replacementNodes = [{ ...node, type: 'heading', level: 1, children: before }, nextParagraph]
            restoreSelectionRef.current = { nodeId: nextParagraph.id, start: 0, end: 0 }
        } else if (node.type === 'heading') {
            if (selectionStart === 0) {
                const previousParagraph = makeEmptyParagraph(`before-${node.id}`)
                replacementNodes = [previousParagraph, { ...node, children: after }]
                restoreSelectionRef.current = { nodeId: previousParagraph.id, start: 0, end: 0 }
            } else {
                const nextHeading = { ...node, id: makeEmptyParagraph(`after-${node.id}`).id, children: after }
                replacementNodes = [{ ...node, children: before }, nextHeading]
                restoreSelectionRef.current = { nodeId: nextHeading.id, start: 0, end: 0 }
            }
        } else if (node.type === 'blockquote') {
            if (selectionStart === 0) {
                const previousParagraph = makeEmptyParagraph(`before-${node.id}`)
                replacementNodes = [previousParagraph, { ...node, children: after }]
                restoreSelectionRef.current = { nodeId: previousParagraph.id, start: 0, end: 0 }
            } else {
                const nextBlockquote = { ...node, id: makeEmptyParagraph(`after-${node.id}`).id, children: after }
                replacementNodes = [{ ...node, children: before }, nextBlockquote]
                restoreSelectionRef.current = { nodeId: nextBlockquote.id, start: 0, end: 0 }
            }
        } else {
            const nextParagraph = makeEmptyParagraph(`after-${node.id}`)
            nextParagraph.children = after
            replacementNodes = [{ ...node, children: before }, nextParagraph]
            restoreSelectionRef.current = { nodeId: nextParagraph.id, start: 0, end: 0 }
        }

        commitDocument({
            ...currentDocument,
            nodes: nodes.flatMap((currentNode) => (currentNode.id === node.id ? replacementNodes : [currentNode])),
        })
        return true
    }, [commitDocument, insertMenu?.nodeId])

    const splitListItemAtCurrentSelection = useCallback((): boolean => {
        const notebookElement = notebookRef.current
        if (!notebookElement) {
            return false
        }

        const selection = window.getSelection()
        const inlineEditableElement = getInlineEditableElementForSelection(selection, notebookElement)
        if (!inlineEditableElement?.classList.contains('MarkdownNotebook__list-item-content')) {
            return false
        }

        const nodeId = inlineEditableElement.dataset.markdownNotebookNodeId
        const itemIndex = Number(inlineEditableElement.dataset.markdownNotebookListItemIndex)
        if (!nodeId || !Number.isInteger(itemIndex)) {
            return false
        }

        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
        const node = nodes.find((currentNode) => currentNode.id === nodeId)
        if (!node || node.type !== 'list') {
            return false
        }

        const itemId = inlineEditableElement.dataset.markdownNotebookListItemId
        const targetItemIndex = getListItemIndex(node.items, itemIndex, itemId)
        const item = node.items[targetItemIndex]
        if (!item) {
            return false
        }

        const expandedSelection = getSelectionRange(inlineEditableElement, node.id)
        const textLength = getInlineText(item.children).length
        const selectionStart = expandedSelection
            ? Math.max(0, Math.min(Math.min(expandedSelection.start, expandedSelection.end), textLength))
            : textLength
        const selectionEnd = expandedSelection
            ? Math.max(selectionStart, Math.min(Math.max(expandedSelection.start, expandedSelection.end), textLength))
            : selectionStart

        if (!textLength && selectionStart === 0 && selectionEnd === 0) {
            if (item.depth > 0) {
                const nextItems = shiftListItemSubtreeDepth(node.items, targetItemIndex, 'out', node.ordered)
                if (!nextItems) {
                    return false
                }

                restoreSelectionRef.current = {
                    nodeId: node.id,
                    listItemIndex: targetItemIndex,
                    listItemId: item.id,
                    start: 0,
                    end: 0,
                }
                commitDocument({
                    ...currentDocument,
                    nodes: nodes.map((currentNode) =>
                        currentNode.id === node.id ? { ...node, items: nextItems } : currentNode
                    ),
                })
                return true
            }

            const replacement = getListItemParagraphReplacement(node, targetItemIndex)
            if (!replacement) {
                return false
            }

            restoreSelectionRef.current = { nodeId: replacement.paragraphId, start: 0, end: 0 }
            commitDocument({
                ...currentDocument,
                nodes: nodes.flatMap((currentNode) =>
                    currentNode.id === node.id ? replacement.replacementNodes : [currentNode]
                ),
            })
            return true
        }

        const [before, selectionAndAfter] = splitInlineNodesAt(item.children, selectionStart)
        const [, after] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)
        const nextItem: NotebookListItem = {
            id: makeListItemId(`split-${node.id}-${item.id ?? String(targetItemIndex)}`),
            children: after,
            depth: item.depth,
            ordered: item.ordered ?? node.ordered,
        }
        const nextItems = [...node.items]
        nextItems[targetItemIndex] = { ...item, children: before }
        nextItems.splice(targetItemIndex + 1, 0, nextItem)
        restoreSelectionRef.current = {
            nodeId: node.id,
            listItemIndex: targetItemIndex + 1,
            listItemId: nextItem.id,
            start: 0,
            end: 0,
        }
        commitDocument({
            ...currentDocument,
            nodes: nodes.map((currentNode) =>
                currentNode.id === node.id ? { ...node, items: nextItems } : currentNode
            ),
        })
        return true
    }, [commitDocument])

    const shiftListItemDepthAtCurrentSelection = useCallback(
        (direction: 'in' | 'out'): boolean => {
            const element = getSelectedInlineEditableElementOfType(
                notebookRef.current,
                'MarkdownNotebook__list-item-content'
            )
            if (!element) {
                return false
            }

            const nodeId = element.dataset.markdownNotebookNodeId
            const itemIndex = Number(element.dataset.markdownNotebookListItemIndex)
            if (!nodeId || !Number.isInteger(itemIndex)) {
                return false
            }

            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const node = nodes.find((currentNode) => currentNode.id === nodeId)
            if (!node || node.type !== 'list') {
                return false
            }

            const itemId = element.dataset.markdownNotebookListItemId
            const targetItemIndex = getListItemIndex(node.items, itemIndex, itemId)
            const item = node.items[targetItemIndex]
            if (!item) {
                return false
            }

            const nextItems = shiftListItemSubtreeDepth(node.items, targetItemIndex, direction, node.ordered)
            if (!nextItems) {
                return false
            }

            const offset = getCollapsedSelectionRange(element, node.id)?.start ?? 0
            restoreSelectionRef.current = {
                nodeId: node.id,
                listItemIndex: targetItemIndex,
                listItemId: item.id,
                start: offset,
                end: offset,
            }
            commitDocument({
                ...currentDocument,
                nodes: nodes.map((currentNode) =>
                    currentNode.id === node.id ? { ...node, items: nextItems } : currentNode
                ),
            })
            return true
        },
        [commitDocument]
    )

    const deleteListItemAtCurrentSelection = useCallback(
        (direction: 'backward' | 'forward'): boolean => {
            const element = getSelectedInlineEditableElementOfType(
                notebookRef.current,
                'MarkdownNotebook__list-item-content'
            )
            if (!element) {
                return false
            }

            const nodeId = element.dataset.markdownNotebookNodeId
            const itemIndex = Number(element.dataset.markdownNotebookListItemIndex)
            if (!nodeId || !Number.isInteger(itemIndex)) {
                return false
            }

            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const node = nodes.find((currentNode) => currentNode.id === nodeId)
            if (!node || node.type !== 'list') {
                return false
            }

            const itemId = element.dataset.markdownNotebookListItemId
            const targetItemIndex = getListItemIndex(node.items, itemIndex, itemId)
            const item = node.items[targetItemIndex]
            if (!item) {
                return false
            }

            const selection = getCollapsedSelectionRange(element, node.id)
            if (!selection || selection.start !== 0 || selection.end !== 0) {
                return false
            }

            if (direction === 'forward' && getInlineText(item.children).length) {
                return false
            }

            if (item.depth > 0) {
                const nextItems = shiftListItemSubtreeDepth(node.items, targetItemIndex, 'out', node.ordered)
                if (!nextItems) {
                    return false
                }

                restoreSelectionRef.current = {
                    nodeId: node.id,
                    listItemIndex: targetItemIndex,
                    listItemId: item.id,
                    start: 0,
                    end: 0,
                }
                commitDocument({
                    ...currentDocument,
                    nodes: nodes.map((currentNode) =>
                        currentNode.id === node.id ? { ...node, items: nextItems } : currentNode
                    ),
                })
                return true
            }

            const replacement = getListItemParagraphReplacement(node, targetItemIndex)
            if (!replacement) {
                return false
            }

            restoreSelectionRef.current = { nodeId: replacement.paragraphId, start: 0, end: 0 }
            commitDocument({
                ...currentDocument,
                nodes: nodes.flatMap((currentNode) =>
                    currentNode.id === node.id ? replacement.replacementNodes : [currentNode]
                ),
            })
            return true
        },
        [commitDocument]
    )

    const insertTableRowAtCurrentSelection = useCallback((): boolean => {
        const element = getSelectedInlineEditableElementOfType(
            notebookRef.current,
            'MarkdownNotebook__table-cell-content'
        )
        const position = element ? getTableCellPositionFromElement(element) : null
        const nodeId = element?.dataset.markdownNotebookNodeId
        if (!element || !position || !nodeId) {
            return false
        }

        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
        const node = nodes.find((currentNode) => currentNode.id === nodeId)
        if (!node || node.type !== 'table') {
            return false
        }

        if (position.section === 'header' && node.rows.length) {
            const targetPosition: TableCellPosition = {
                section: 'body',
                rowIndex: 0,
                columnIndex: position.columnIndex,
            }
            const cellElement = tableCellRefs.current[getTableCellRefKey(node.id, targetPosition)]
            if (cellElement) {
                cellElement.focus()
                restoreSelection(cellElement, 0, 0)
            }
            return true
        }

        const columnCount = getTableColumnCount(node)
        const insertIndex =
            position.section === 'header' ? 0 : Math.max(0, Math.min(position.rowIndex + 1, node.rows.length))
        const nextRows = node.rows.map((row) => normalizeTableRow(row, columnCount))
        nextRows.splice(insertIndex, 0, makeEmptyTableRow(columnCount))
        restoreSelectionRef.current = {
            nodeId: node.id,
            tableCell: { section: 'body', rowIndex: insertIndex, columnIndex: position.columnIndex },
            start: 0,
            end: 0,
        }
        commitDocument({
            ...currentDocument,
            nodes: nodes.map((currentNode) => (currentNode.id === node.id ? { ...node, rows: nextRows } : currentNode)),
        })
        return true
    }, [commitDocument])

    const startInsertMenuAtCurrentTextSelection = useCallback(
        (query: string = ''): boolean => {
            const notebookElement = notebookRef.current
            if (!notebookElement) {
                return false
            }

            const selection = window.getSelection()
            const inlineEditableElement = getInlineEditableElementForSelection(selection, notebookElement)
            if (
                !inlineEditableElement?.classList.contains('MarkdownNotebook__text-block') ||
                inlineEditableElement.classList.contains('MarkdownNotebook__text-block--ai-prompt')
            ) {
                return false
            }

            const nodeId = inlineEditableElement.dataset.markdownNotebookNodeId
            if (!nodeId) {
                return false
            }

            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const nodeIndex = nodes.findIndex((node) => node.id === nodeId)
            const node = nodes[nodeIndex]
            if (!node || !isTextBlockNode(node)) {
                return false
            }

            const expandedSelection = getSelectionRange(inlineEditableElement, node.id)
            const textLength = getInlineText(node.children).length
            const selectionStart = expandedSelection
                ? Math.max(0, Math.min(Math.min(expandedSelection.start, expandedSelection.end), textLength))
                : textLength
            const selectionEnd = expandedSelection
                ? Math.max(
                      selectionStart,
                      Math.min(Math.max(expandedSelection.start, expandedSelection.end), textLength)
                  )
                : selectionStart
            if (selectionStart !== 0 || selectionEnd !== 0) {
                return false
            }

            const [before, selectionAndAfter] = splitInlineNodesAt(node.children, selectionStart)
            const [, after] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)
            const commandNode = makeEmptyParagraph(`slash-command-${node.id}`)
            commandNode.children = query ? [{ type: 'text', text: query }] : []
            const replacementNodes: NotebookBlockNode[] = []

            if (nodeIndex === 0) {
                replacementNodes.push({ ...node, type: 'heading', level: 1, children: normalizeInlineNodes(before) })
            } else if (getInlineText(before).length > 0) {
                replacementNodes.push({ ...node, children: normalizeInlineNodes(before) })
            }

            replacementNodes.push(commandNode)

            if (getInlineText(after).length > 0) {
                const afterNodeId = makeEmptyParagraph(`after-slash-command-${node.id}`).id
                const afterNode =
                    nodeIndex === 0
                        ? { id: afterNodeId, type: 'paragraph' as const, children: normalizeInlineNodes(after) }
                        : {
                              ...node,
                              id: afterNodeId,
                              children: normalizeInlineNodes(after),
                          }
                replacementNodes.push(afterNode)
            }

            restoreSelectionRef.current = {
                nodeId: commandNode.id,
                start: query.length,
                end: query.length,
            }
            onInteractionStateChange?.(true)
            setInsertMenu({ nodeId: commandNode.id, query, selectedIndex: 0, mode: 'tools', detached: true })
            commitDocument({
                ...currentDocument,
                nodes: nodes.flatMap((currentNode) => (currentNode.id === node.id ? replacementNodes : [currentNode])),
            })
            return true
        },
        [commitDocument, onInteractionStateChange]
    )

    // Backspace at the start of a text block whose previous sibling is not a text block: the
    // previous block must never be deleted wholesale — the caret moves into its trailing edge
    // (merging the text into a trailing list item where possible) so further backspaces delete
    // characters.
    const mergeTextBlockIntoPreviousBlock = useCallback(
        (nodeIndex: number): boolean => {
            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const node = nodes[nodeIndex]
            const previousNode = nodes[nodeIndex - 1]
            if (!node || !isTextBlockNode(node) || !previousNode || isTextBlockNode(previousNode)) {
                return false
            }

            const isEmptyTextBlock = !getInlineText(node.children).length

            if (previousNode.type === 'list') {
                const lastItemIndex = previousNode.items.length - 1
                const lastItem = previousNode.items[lastItemIndex]
                if (!lastItem) {
                    return false
                }

                const lastItemTextLength = getInlineText(lastItem.children).length
                restoreSelectionRef.current = {
                    nodeId: previousNode.id,
                    listItemIndex: lastItemIndex,
                    listItemId: lastItem.id,
                    start: lastItemTextLength,
                    end: lastItemTextLength,
                }
                commitDocument({
                    ...currentDocument,
                    nodes: nodes.flatMap((currentNode, index) => {
                        if (index === nodeIndex - 1 && currentNode.type === 'list') {
                            return [
                                {
                                    ...currentNode,
                                    items: currentNode.items.map((item, itemIndex) =>
                                        itemIndex === lastItemIndex
                                            ? {
                                                  ...item,
                                                  children: normalizeInlineNodes([...item.children, ...node.children]),
                                              }
                                            : item
                                    ),
                                },
                            ]
                        }
                        if (index === nodeIndex) {
                            return []
                        }
                        return [currentNode]
                    }),
                })
                return true
            }

            if (previousNode.type === 'code') {
                const codeTextLength = previousNode.text.length
                if (isEmptyTextBlock) {
                    restoreSelectionRef.current = {
                        nodeId: previousNode.id,
                        start: codeTextLength,
                        end: codeTextLength,
                    }
                    commitDocument({
                        ...currentDocument,
                        nodes: nodes.filter((_, index) => index !== nodeIndex),
                    })
                    return true
                }

                const element = blockRefs.current[previousNode.id]
                if (element) {
                    element.focus()
                    restoreSelection(element, codeTextLength, codeTextLength)
                }
                return true
            }

            if (previousNode.type === 'table') {
                const lastCellPosition = getTableEdgeCellPosition(previousNode, 'previous')
                if (!lastCellPosition) {
                    return false
                }

                const offset = getInlineText(
                    getTableCellAtPosition(previousNode, lastCellPosition)?.children ?? []
                ).length
                if (isEmptyTextBlock) {
                    restoreSelectionRef.current = {
                        nodeId: previousNode.id,
                        tableCell: lastCellPosition,
                        start: offset,
                        end: offset,
                    }
                    commitDocument({
                        ...currentDocument,
                        nodes: nodes.filter((_, index) => index !== nodeIndex),
                    })
                    return true
                }

                const element = tableCellRefs.current[getTableCellRefKey(previousNode.id, lastCellPosition)]
                if (element) {
                    element.focus()
                    restoreSelection(element, offset, offset)
                }
                return true
            }

            if (previousNode.type === 'component') {
                if (isEmptyTextBlock && node.type === 'paragraph') {
                    focusNodeRef.current = previousNode.id
                    commitDocument({
                        ...currentDocument,
                        nodes: nodes.filter((_, index) => index !== nodeIndex),
                    })
                    return true
                }

                blockRefs.current[previousNode.id]?.focus()
                return true
            }

            return false
        },
        [commitDocument]
    )

    const deleteTextAtCurrentSelection = useCallback(
        (direction: 'backward' | 'forward'): boolean => {
            const notebookElement = notebookRef.current
            if (!notebookElement) {
                return false
            }

            const selection = window.getSelection()
            const inlineEditableElement = getInlineEditableElementForSelection(selection, notebookElement)
            if (!inlineEditableElement?.classList.contains('MarkdownNotebook__text-block')) {
                return false
            }

            const nodeId = inlineEditableElement.dataset.markdownNotebookNodeId
            if (!nodeId) {
                return false
            }

            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const nodeIndex = nodes.findIndex((node) => node.id === nodeId)
            const node = nodes[nodeIndex]
            if (!node || !isTextBlockNode(node)) {
                return false
            }

            const expandedSelection = getSelectionRange(inlineEditableElement, node.id)
            const textLength = getInlineText(node.children).length
            const selectionStart = expandedSelection
                ? Math.max(0, Math.min(Math.min(expandedSelection.start, expandedSelection.end), textLength))
                : textLength
            const selectionEnd = expandedSelection
                ? Math.max(
                      selectionStart,
                      Math.min(Math.max(expandedSelection.start, expandedSelection.end), textLength)
                  )
                : selectionStart

            if (selectionStart !== selectionEnd) {
                const [beforeSelection, selectionAndAfter] = splitInlineNodesAt(node.children, selectionStart)
                const [, afterSelection] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)
                const nextChildren = normalizeInlineNodes([...beforeSelection, ...afterSelection])

                restoreSelectionRef.current = { nodeId: node.id, start: selectionStart, end: selectionStart }
                commitDocument({
                    ...currentDocument,
                    nodes: nodes.map((currentNode) =>
                        currentNode.id === node.id && isTextBlockNode(currentNode)
                            ? { ...currentNode, children: nextChildren }
                            : currentNode
                    ),
                })
                return true
            }

            if (direction === 'forward' || selectionStart !== 0 || nodeIndex <= 0) {
                return false
            }

            const previousNode = nodes[nodeIndex - 1]
            if (textLength === 0 && node.type === 'paragraph' && previousNode?.type === 'component') {
                focusNodeRef.current = previousNode.id
                commitDocument({
                    ...currentDocument,
                    nodes: nodes.filter((_, index) => index !== nodeIndex),
                })
                return true
            }

            if (
                (node.type === 'heading' || node.type === 'blockquote') &&
                (!isTextBlockNode(previousNode) || !textBlocksShareContinuationStyle(previousNode, node))
            ) {
                restoreSelectionRef.current = { nodeId: node.id, start: 0, end: 0 }
                commitDocument({
                    ...currentDocument,
                    nodes: nodes.map((currentNode) =>
                        currentNode.id === node.id && isTextBlockNode(currentNode)
                            ? { ...currentNode, type: 'paragraph', level: undefined }
                            : currentNode
                    ),
                })
                return true
            }

            if (isTextBlockNode(previousNode)) {
                const previousTextLength = getInlineText(previousNode.children).length
                const mergedNode: NotebookTextBlockNode = {
                    ...previousNode,
                    children: normalizeInlineNodes([...previousNode.children, ...node.children]),
                }

                restoreSelectionRef.current = {
                    nodeId: previousNode.id,
                    start: previousTextLength,
                    end: previousTextLength,
                }
                commitDocument({
                    ...currentDocument,
                    nodes: nodes.flatMap((currentNode, index) => {
                        if (index === nodeIndex - 1) {
                            return [mergedNode]
                        }
                        if (index === nodeIndex) {
                            return []
                        }
                        return [currentNode]
                    }),
                })
                return true
            }

            return mergeTextBlockIntoPreviousBlock(nodeIndex)
        },
        [commitDocument, mergeTextBlockIntoPreviousBlock]
    )

    useEffect(() => {
        const notebookElement = notebookRef.current
        if (!notebookElement) {
            return
        }

        const handleBeforeInput = (event: Event): void => {
            if (mode !== 'edit') {
                return
            }

            if (
                event.target instanceof HTMLElement &&
                (event.target.closest('.MarkdownNotebook__debug-drawer') || isNativeEditableElement(event.target))
            ) {
                return
            }

            const nativeEvent = event as InputEvent
            if (
                nativeEvent.inputType === 'insertParagraph' &&
                (splitListItemAtCurrentSelection() ||
                    insertTableRowAtCurrentSelection() ||
                    splitTextBlockAtCurrentSelection())
            ) {
                event.preventDefault()
                event.stopPropagation()
                return
            }

            if (
                nativeEvent.inputType === 'insertText' &&
                nativeEvent.data === '/' &&
                startInsertMenuAtCurrentTextSelection()
            ) {
                event.preventDefault()
                event.stopPropagation()
                return
            }

            if (
                nativeEvent.inputType === 'insertText' &&
                typeof nativeEvent.data === 'string' &&
                nativeEvent.data.length > 0 &&
                deleteSelectedNotebookBlocks(nativeEvent.data)
            ) {
                event.preventDefault()
                event.stopPropagation()
                return
            }

            if (
                (nativeEvent.inputType === 'deleteContentBackward' ||
                    nativeEvent.inputType === 'deleteContentForward') &&
                deleteSelectedNotebookBlocks()
            ) {
                event.preventDefault()
                event.stopPropagation()
                return
            }

            if (
                (nativeEvent.inputType === 'deleteContentBackward' ||
                    nativeEvent.inputType === 'deleteContentForward') &&
                (deleteListItemAtCurrentSelection(
                    nativeEvent.inputType === 'deleteContentBackward' ? 'backward' : 'forward'
                ) ||
                    deleteTextAtCurrentSelection(
                        nativeEvent.inputType === 'deleteContentBackward' ? 'backward' : 'forward'
                    ))
            ) {
                event.preventDefault()
                event.stopPropagation()
                return
            }

            if (nativeEvent.inputType !== 'historyUndo' && nativeEvent.inputType !== 'historyRedo') {
                return
            }

            if (nativeEvent.inputType === 'historyUndo') {
                undoHistory()
            } else {
                redoHistory()
            }

            event.preventDefault()
            event.stopPropagation()
        }

        notebookElement.addEventListener('beforeinput', handleBeforeInput, true)
        return () => notebookElement.removeEventListener('beforeinput', handleBeforeInput, true)
    }, [
        deleteListItemAtCurrentSelection,
        deleteSelectedNotebookBlocks,
        deleteTextAtCurrentSelection,
        insertTableRowAtCurrentSelection,
        mode,
        redoHistory,
        splitListItemAtCurrentSelection,
        splitTextBlockAtCurrentSelection,
        startInsertMenuAtCurrentTextSelection,
        undoHistory,
    ])

    const updateNode = useCallback(
        (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null): void => {
            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            let didUpdate = false
            const nextNodes = nodes.flatMap((node) => {
                if (didUpdate || node.id !== nodeId) {
                    return [node]
                }
                didUpdate = true
                const updatedNode = updater(cloneNotebookNode(node))
                return updatedNode ? [updatedNode] : []
            })

            commitDocument({
                ...currentDocument,
                nodes: nextNodes,
            })
        },
        [commitDocument]
    )

    const replaceNode = useCallback(
        (nodeId: string, nextNode: NotebookBlockNode): void => {
            updateNode(nodeId, () => nextNode)
        },
        [updateNode]
    )

    const replaceNodeWithInsertedComponent = useCallback(
        (nodeId: string, nextNode: NotebookComponentBlockNode): void => {
            const definition = getMarkdownNotebookComponentDefinition(mergedRegistry, nextNode.tagName)
            const insertedPanels = getComponentPanelVisibility(nextNode, INSERTED_COMPONENT_PANEL_VISIBILITY)
            const insertedNode = withPersistedComponentPanelProps(nextNode, definition, insertedPanels)
            focusNodeRef.current = nextNode.id
            replaceNode(nodeId, insertedNode)
        },
        [mergedRegistry, replaceNode]
    )

    const replaceNodeWithNodes = useCallback(
        (nodeId: string, replacementNodes: NotebookBlockNode[]): void => {
            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            let didReplace = false
            commitDocument({
                ...currentDocument,
                nodes: nodes.flatMap((node) => {
                    if (didReplace || node.id !== nodeId) {
                        return [node]
                    }
                    didReplace = true
                    return replacementNodes
                }),
            })
        },
        [commitDocument]
    )

    const insertNodesAfterNode = useCallback(
        (nodeId: string, insertedNodes: NotebookBlockNode[]): void => {
            if (!insertedNodes.length) {
                return
            }

            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const nodeIndex = nodes.findIndex((node) => node.id === nodeId)
            if (nodeIndex === -1) {
                return
            }

            commitDocument({
                ...currentDocument,
                nodes: [...nodes.slice(0, nodeIndex + 1), ...insertedNodes, ...nodes.slice(nodeIndex + 1)],
            })

            const firstInsertedNode = insertedNodes[0]
            if (firstInsertedNode.type === 'component') {
                focusNodeRef.current = firstInsertedNode.id
            } else if (isTextBlockNode(firstInsertedNode)) {
                const offset = getInlineText(firstInsertedNode.children).length
                restoreSelectionRef.current = { nodeId: firstInsertedNode.id, start: offset, end: offset }
            }
        },
        [commitDocument]
    )

    const insertMarkdownAfterNode = useCallback(
        (nodeId: string, markdown: string, seed: string): boolean => {
            const pastedNodes = rekeyNotebookNodes(parseMarkdownNotebook(markdown).nodes, seed)
            if (!pastedNodes.length) {
                return false
            }

            insertNodesAfterNode(nodeId, pastedNodes)
            return true
        },
        [insertNodesAfterNode]
    )

    const deleteNodeBefore = useCallback(
        (nodeId: string, options: { requireSameTextStyle?: boolean } = {}): boolean => {
            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const nodeIndex = nodes.findIndex((node) => node.id === nodeId)
            if (nodeIndex <= 0) {
                return false
            }

            const previousNode = nodes[nodeIndex - 1]
            const currentNode = nodes[nodeIndex]
            if (isTextBlockNode(previousNode) && isTextBlockNode(currentNode)) {
                if (options.requireSameTextStyle && !textBlocksShareContinuationStyle(previousNode, currentNode)) {
                    return false
                }

                const previousTextLength = getInlineText(previousNode.children).length
                const mergedNode: NotebookTextBlockNode = {
                    ...previousNode,
                    children: normalizeInlineNodes([...previousNode.children, ...currentNode.children]),
                }

                restoreSelectionRef.current = {
                    nodeId: previousNode.id,
                    start: previousTextLength,
                    end: previousTextLength,
                }
                commitDocument({
                    ...currentDocument,
                    nodes: nodes.flatMap((node, index) => {
                        if (index === nodeIndex - 1) {
                            return [mergedNode]
                        }
                        if (index === nodeIndex) {
                            return []
                        }
                        return [node]
                    }),
                })
                return true
            }

            if (options.requireSameTextStyle) {
                return false
            }

            return mergeTextBlockIntoPreviousBlock(nodeIndex)
        },
        [commitDocument, mergeTextBlockIntoPreviousBlock]
    )

    const openAIPrompt = useCallback(
        (nodeId: string, options?: { source?: 'slash' | 'selection'; selectedMarkdown?: string }): void => {
            onInteractionStateChange?.(true)
            updateNode(nodeId, (currentNode) => {
                if (!isTextBlockNode(currentNode) && currentNode.type !== 'component') {
                    return currentNode
                }
                const promptProps: NotebookComponentProps = { question: '' }
                if (options?.source === 'selection') {
                    promptProps.source = 'selection'
                    promptProps.selectedMarkdown = options.selectedMarkdown ?? ''
                }
                return {
                    id: currentNode.id,
                    type: 'component',
                    tagName: 'Prompt',
                    props: promptProps,
                }
            })
            setInsertMenu({
                nodeId,
                query: '',
                selectedIndex: 0,
                mode: 'ai',
                source: options?.source ?? 'slash',
                selectedMarkdown: options?.selectedMarkdown,
            })
        },
        [onInteractionStateChange, updateNode]
    )

    const updateAIPromptQuery = (nodeId: string, query: string): void => {
        setInsertMenu((currentMenu) => {
            if (!currentMenu || currentMenu.nodeId !== nodeId || currentMenu.mode !== 'ai') {
                return currentMenu
            }
            return { ...currentMenu, query }
        })
    }

    const renderedNodes = getRenderedNodes()
    const showInsertBoundaries = mode === 'edit' && document.nodes.length > 0
    const placeholderNodeId = hasNotebookContent(renderedNodes) ? null : renderedNodes[0]?.id
    const insertCommands = useMemo(
        () =>
            buildInsertCommands(
                mergedRegistry,
                replaceNodeWithInsertedComponent,
                replaceNode,
                (nodeId) => {
                    restoreSelectionRef.current = { nodeId, start: 0, end: 0 }
                },
                (nodeId) => {
                    restoreSelectionRef.current = {
                        nodeId,
                        tableCell: { section: 'header', rowIndex: 0, columnIndex: 0 },
                        start: 0,
                        end: 8,
                    }
                },
                (nodeId) => {
                    restoreSelectionRef.current = { nodeId, start: 0, end: 0 }
                },
                onAskAI ? openAIPrompt : undefined
            ),
        [mergedRegistry, replaceNodeWithInsertedComponent, replaceNode, onAskAI, openAIPrompt]
    )

    function getRenderedNodes(): NotebookBlockNode[] {
        if (document.nodes.length || mode === 'view') {
            return document.nodes
        }
        return [emptyNodeRef.current]
    }

    useEffect(() => {
        const componentNodeIds = new Set(document.nodes.flatMap((node) => (node.type === 'component' ? [node.id] : [])))
        const initializedComponentPanelNodeIds = initializedComponentPanelNodeIdsRef.current
        if (initializedComponentPanelNodeIds === null) {
            initializedComponentPanelNodeIdsRef.current = componentNodeIds
            return
        }

        const insertedComponentNodeIds = [...componentNodeIds].filter(
            (nodeId) => !initializedComponentPanelNodeIds.has(nodeId)
        )
        initializedComponentPanelNodeIdsRef.current = componentNodeIds
        if (mode !== 'edit' || !insertedComponentNodeIds.length) {
            return
        }

        const insertedComponentNodeIdSet = new Set(insertedComponentNodeIds)
        const nextNodes = document.nodes.map((node) => {
            if (node.type !== 'component' || !insertedComponentNodeIdSet.has(node.id)) {
                return node
            }

            const definition = getMarkdownNotebookComponentDefinition(mergedRegistry, node.tagName)
            const insertedPanels = getComponentPanelVisibility(node, INSERTED_COMPONENT_PANEL_VISIBILITY)
            return withPersistedComponentPanelProps(node, definition, insertedPanels)
        })
        if (areNotebookDocumentsEqual(document, { ...document, nodes: nextNodes })) {
            return
        }

        commitDocument(
            {
                ...document,
                nodes: nextNodes,
            },
            {
                addToHistory: false,
            }
        )
    }, [commitDocument, document, mergedRegistry, mode])

    const updateFloatingToolbarFromSelection = useCallback((): void => {
        clearFloatingToolbarRevealTimeout()
        const pointerAnchor = floatingToolbarPointerAnchorRef.current
        floatingToolbarPointerAnchorRef.current = null

        if (mode !== 'edit') {
            floatingToolbarPositionLockRef.current = null
            setFloatingToolbar(null)
            return
        }

        const selection = window.getSelection()
        if (!selection || selection.rangeCount === 0) {
            if (isFormattingToolbarFocused()) {
                return
            }
            floatingToolbarPositionLockRef.current = null
            setFloatingToolbar(null)
            return
        }

        const notebookElement = notebookRef.current
        const selectedMarkdown = notebookElement
            ? getSelectedNotebookMarkdown(
                  selection,
                  notebookElement,
                  documentRef.current.nodes,
                  blockRefs.current,
                  listItemRefs.current
              )
            : null
        const textRanges = getSelectedTextRanges(selection, documentRef.current.nodes, blockRefs.current)
        const codeRanges = getSelectedCodeRanges(selection, documentRef.current.nodes, blockRefs.current)
        const listItemRanges = getSelectedListItemRanges(selection, documentRef.current.nodes, listItemRefs.current)
        if ((!textRanges.length && !codeRanges.length && !listItemRanges.length) || !selectedMarkdown) {
            if (isFormattingToolbarFocused()) {
                return
            }
            floatingToolbarPositionLockRef.current = null
            setFloatingToolbar(null)
            return
        }

        const domRange = selection.getRangeAt(0)

        const selectionRect = getSelectionClientRect(domRange)
        if (!selectionRect) {
            floatingToolbarPositionLockRef.current = null
            setFloatingToolbar(null)
            return
        }

        const firstSelectedNodeId = textRanges[0]?.node.id ?? codeRanges[0]?.node.id ?? listItemRanges[0]?.node.id
        const firstSelectedElement = firstSelectedNodeId ? blockRefs.current[firstSelectedNodeId] : null
        const lineHeight = firstSelectedElement ? getElementLineHeight(firstSelectedElement) : 24
        const shouldPlaceBelow = pointerAnchor
            ? pointerAnchor.placement === 'below'
            : selectionRect.top < FLOATING_TOOLBAR_ESTIMATED_HEIGHT + lineHeight
        const pointerOverlapsSelection =
            pointerAnchor && pointerAnchor.y >= selectionRect.top && pointerAnchor.y <= selectionRect.bottom
        const toolbarTop = pointerAnchor
            ? Math.round(
                  shouldPlaceBelow
                      ? pointerOverlapsSelection
                          ? selectionRect.bottom + FLOATING_TOOLBAR_GAP
                          : pointerAnchor.y + FLOATING_TOOLBAR_GAP
                      : pointerOverlapsSelection
                        ? selectionRect.top
                        : pointerAnchor.y
              )
            : Math.round(shouldPlaceBelow ? selectionRect.bottom + lineHeight : selectionRect.top)
        const toolbarLeft = pointerAnchor
            ? Math.round(pointerAnchor.x)
            : Math.round(selectionRect.left + selectionRect.width / 2)
        const lockedPosition = floatingToolbarPositionLockRef.current

        setFloatingToolbar({
            textRanges,
            codeRanges,
            listItemRanges,
            selectedMarkdown,
            placement: lockedPosition?.placement ?? (shouldPlaceBelow ? 'below' : 'above'),
            top: lockedPosition?.top ?? toolbarTop,
            left: lockedPosition?.left ?? Math.min(window.innerWidth - 16, Math.max(16, toolbarLeft)),
        })
    }, [clearFloatingToolbarRevealTimeout, mode])

    const scheduleFloatingToolbarUpdateFromSelection = useCallback(
        (delayMs: number = 0): void => {
            clearFloatingToolbarRevealTimeout()
            if (delayMs <= 0) {
                floatingToolbarRevealAfterRef.current = 0
                updateFloatingToolbarFromSelection()
                return
            }

            setFloatingToolbar(null)
            floatingToolbarRevealTimeoutRef.current = window.setTimeout(() => {
                floatingToolbarRevealTimeoutRef.current = null
                updateFloatingToolbarFromSelection()
            }, delayMs)
        },
        [clearFloatingToolbarRevealTimeout, updateFloatingToolbarFromSelection]
    )

    useEffect(() => clearFloatingToolbarRevealTimeout, [clearFloatingToolbarRevealTimeout])

    const updateSelectedComponentBlocksFromSelection = useCallback((): void => {
        const nextSelectedComponentNodeIds =
            mode === 'edit'
                ? getSelectedComponentNodeIds(window.getSelection(), documentRef.current.nodes, blockRefs.current)
                : new Set<string>()

        setSelectedComponentNodeIds((currentSelectedComponentNodeIds) =>
            setsEqual(currentSelectedComponentNodeIds, nextSelectedComponentNodeIds)
                ? currentSelectedComponentNodeIds
                : nextSelectedComponentNodeIds
        )
    }, [mode])

    useEffect(() => {
        if (mode !== 'edit') {
            setFloatingToolbar(null)
            setSelectedComponentNodeIds(new Set())
            clearFloatingToolbarRevealTimeout()
            isTextSelectionPointerActiveRef.current = false
            floatingToolbarRevealAfterRef.current = 0
            return
        }

        const notebookElement = notebookRef.current
        if (!notebookElement) {
            return
        }

        const handleDocumentSelectionChange = (): void => {
            if (isTextSelectionPointerActiveRef.current) {
                setFloatingToolbar(null)
            } else {
                scheduleFloatingToolbarUpdateFromSelection(
                    Math.max(0, floatingToolbarRevealAfterRef.current - Date.now())
                )
            }
            updateSelectedComponentBlocksFromSelection()
        }

        const handleDocumentPointerStart = (event: MouseEvent | PointerEvent | TouchEvent): void => {
            if (event.target instanceof HTMLElement && event.target.closest('.MarkdownNotebook__format-toolbar')) {
                return
            }

            floatingToolbarPositionLockRef.current = null
        }

        window.document.addEventListener('selectionchange', handleDocumentSelectionChange)
        window.document.addEventListener('mousedown', handleDocumentPointerStart, true)
        window.document.addEventListener('pointerdown', handleDocumentPointerStart, true)
        window.document.addEventListener('touchstart', handleDocumentPointerStart, true)
        window.addEventListener('resize', handleDocumentSelectionChange)
        window.addEventListener('scroll', handleDocumentSelectionChange, true)

        return () => {
            window.document.removeEventListener('selectionchange', handleDocumentSelectionChange)
            window.document.removeEventListener('mousedown', handleDocumentPointerStart, true)
            window.document.removeEventListener('pointerdown', handleDocumentPointerStart, true)
            window.document.removeEventListener('touchstart', handleDocumentPointerStart, true)
            window.removeEventListener('resize', handleDocumentSelectionChange)
            window.removeEventListener('scroll', handleDocumentSelectionChange, true)
        }
    }, [
        mode,
        clearFloatingToolbarRevealTimeout,
        scheduleFloatingToolbarUpdateFromSelection,
        updateSelectedComponentBlocksFromSelection,
    ])

    const handleSelectionChange = (): void => {
        if (isTextSelectionPointerActiveRef.current) {
            clearFloatingToolbarRevealTimeout()
            setFloatingToolbar(null)
            return
        }

        scheduleFloatingToolbarUpdateFromSelection(Math.max(0, floatingToolbarRevealAfterRef.current - Date.now()))
    }

    const updateTextSelectionPointerPoint = useCallback((clientX: number, clientY: number): void => {
        const pointerState = textSelectionPointerStateRef.current
        if (!pointerState) {
            return
        }

        pointerState.lastX = clientX
        pointerState.lastY = clientY
    }, [])

    const finishTextSelectionPointer = useCallback(
        (clientX?: number, clientY?: number): void => {
            const pointerState = textSelectionPointerStateRef.current
            if (pointerState) {
                if (clientX !== undefined && clientY !== undefined) {
                    pointerState.lastX = clientX
                    pointerState.lastY = clientY
                }

                floatingToolbarPointerAnchorRef.current = {
                    x: pointerState.lastX,
                    y: pointerState.lastY,
                    placement: pointerState.lastY >= pointerState.originY ? 'below' : 'above',
                }
            }

            textSelectionPointerStateRef.current = null
            isTextSelectionPointerActiveRef.current = false
            floatingToolbarRevealAfterRef.current = Date.now() + FLOATING_TOOLBAR_REVEAL_DELAY_MS
            scheduleFloatingToolbarUpdateFromSelection(FLOATING_TOOLBAR_REVEAL_DELAY_MS)
        },
        [scheduleFloatingToolbarUpdateFromSelection]
    )

    useEffect(() => {
        if (mode !== 'edit') {
            isTextSelectionPointerActiveRef.current = false
            floatingToolbarRevealAfterRef.current = 0
            textSelectionPointerStateRef.current = null
            floatingToolbarPointerAnchorRef.current = null
            return
        }

        const handleMouseMove = (event: MouseEvent): void => {
            if (isTextSelectionPointerActiveRef.current) {
                updateTextSelectionPointerPoint(event.clientX, event.clientY)
            }
        }

        const handleMouseUp = (event: MouseEvent): void => {
            if (!isTextSelectionPointerActiveRef.current) {
                return
            }

            finishTextSelectionPointer(event.clientX, event.clientY)
        }

        const handlePointerMove = (event: PointerEvent): void => {
            if (isTextSelectionPointerActiveRef.current) {
                updateTextSelectionPointerPoint(event.clientX, event.clientY)
            }
        }

        const handlePointerEnd = (event: PointerEvent): void => {
            if (!isTextSelectionPointerActiveRef.current) {
                return
            }

            finishTextSelectionPointer(event.clientX, event.clientY)
        }

        const handleTouchMove = (event: TouchEvent): void => {
            if (!isTextSelectionPointerActiveRef.current) {
                return
            }

            const touch = event.touches[0]
            if (touch) {
                updateTextSelectionPointerPoint(touch.clientX, touch.clientY)
            }
        }

        const handleTouchEnd = (event: TouchEvent): void => {
            if (!isTextSelectionPointerActiveRef.current) {
                return
            }

            const changedTouch = event.changedTouches[0]
            finishTextSelectionPointer(changedTouch?.clientX, changedTouch?.clientY)
        }

        window.document.addEventListener('mousemove', handleMouseMove, true)
        window.document.addEventListener('mouseup', handleMouseUp)
        window.document.addEventListener('pointermove', handlePointerMove, true)
        window.document.addEventListener('pointerup', handlePointerEnd, true)
        window.document.addEventListener('pointercancel', handlePointerEnd, true)
        window.document.addEventListener('touchmove', handleTouchMove, true)
        window.document.addEventListener('touchend', handleTouchEnd, true)
        window.document.addEventListener('touchcancel', handleTouchEnd, true)

        return () => {
            window.document.removeEventListener('mousemove', handleMouseMove, true)
            window.document.removeEventListener('mouseup', handleMouseUp)
            window.document.removeEventListener('pointermove', handlePointerMove, true)
            window.document.removeEventListener('pointerup', handlePointerEnd, true)
            window.document.removeEventListener('pointercancel', handlePointerEnd, true)
            window.document.removeEventListener('touchmove', handleTouchMove, true)
            window.document.removeEventListener('touchend', handleTouchEnd, true)
            window.document.removeEventListener('touchcancel', handleTouchEnd, true)
        }
    }, [finishTextSelectionPointer, mode, updateTextSelectionPointerPoint])

    const startTextSelectionPointer = (event: TextSelectionPointerStartEvent): void => {
        if (mode !== 'edit') {
            return
        }

        const beginTextSelectionPointer = (clientX: number, clientY: number): void => {
            clearFloatingToolbarRevealTimeout()
            isTextSelectionPointerActiveRef.current = true
            floatingToolbarRevealAfterRef.current = 0
            textSelectionPointerStateRef.current = {
                originX: clientX,
                originY: clientY,
                lastX: clientX,
                lastY: clientY,
            }
            floatingToolbarPointerAnchorRef.current = null
            floatingToolbarPositionLockRef.current = null
            setFloatingToolbar(null)
        }

        if ('touches' in event) {
            if (event.touches.length !== 1) {
                return
            }

            const touch = event.touches[0]
            beginTextSelectionPointer(touch.clientX, touch.clientY)
            return
        }

        if ('pointerId' in event) {
            if (event.isPrimary === false || event.pointerType === 'touch' || event.button !== 0) {
                return
            }

            beginTextSelectionPointer(event.clientX, event.clientY)
            return
        }

        if ((window as Window & { PointerEvent?: typeof PointerEvent }).PointerEvent || event.button !== 0) {
            return
        }

        beginTextSelectionPointer(event.clientX, event.clientY)
    }

    const copyMarkdownToNotebookClipboard = (markdown: string): void => {
        notebookClipboardMarkdownRef.current = markdown
        writeSystemClipboardText(markdown)
    }

    const pasteNotebookClipboardAfterNode = (nodeId: string): void => {
        const fallbackMarkdown = notebookClipboardMarkdownRef.current
        const pasteMarkdown = (markdown: string | null): void => {
            const nextMarkdown = markdown || fallbackMarkdown
            if (!nextMarkdown) {
                return
            }

            insertMarkdownAfterNode(nodeId, nextMarkdown, `component-keyboard-paste-${nodeId}-${nextMarkdown.length}`)
        }

        void readSystemClipboardText().then(pasteMarkdown)
    }

    const handleCopy = (event: ReactClipboardEvent<HTMLDivElement>): void => {
        if (event.target instanceof HTMLElement && isNativeEditableElement(event.target)) {
            return
        }

        const selection = window.getSelection()
        if (getComponentNodeForSelection(selection, documentRef.current.nodes, blockRefs.current)) {
            return
        }

        const notebookElement = notebookRef.current
        const markdown = notebookElement
            ? getSelectedNotebookMarkdown(
                  selection,
                  notebookElement,
                  documentRef.current.nodes,
                  blockRefs.current,
                  listItemRefs.current
              )
            : null
        if (markdown) {
            event.preventDefault()
            setClipboardMarkdown(event.clipboardData, markdown)
            return
        }

        const focusedComponentNode = getFocusedComponentNode(
            window.document.activeElement,
            documentRef.current.nodes,
            blockRefs.current
        )
        if (focusedComponentNode) {
            const markdown = serializeNotebookNodes([focusedComponentNode])
            notebookClipboardMarkdownRef.current = markdown
            event.preventDefault()
            setClipboardMarkdown(event.clipboardData, markdown)
            return
        }
    }

    const handleCut = (event: ReactClipboardEvent<HTMLDivElement>): void => {
        if (mode !== 'edit' || (event.target instanceof HTMLElement && isNativeEditableElement(event.target))) {
            return
        }

        const selection = window.getSelection()
        if (getComponentNodeForSelection(selection, documentRef.current.nodes, blockRefs.current)) {
            return
        }

        const notebookElement = notebookRef.current
        const markdown = notebookElement
            ? getSelectedNotebookMarkdown(
                  selection,
                  notebookElement,
                  documentRef.current.nodes,
                  blockRefs.current,
                  listItemRefs.current
              )
            : null
        if (markdown) {
            event.preventDefault()
            notebookClipboardMarkdownRef.current = markdown
            setClipboardMarkdown(event.clipboardData, markdown)
            if (!deleteSelectedNotebookBlocks()) {
                deleteTextAtCurrentSelection('forward')
            }
            return
        }

        const focusedComponentNode = getFocusedComponentNode(
            window.document.activeElement,
            documentRef.current.nodes,
            blockRefs.current
        )
        if (focusedComponentNode) {
            const markdown = serializeNotebookNodes([focusedComponentNode])
            notebookClipboardMarkdownRef.current = markdown
            event.preventDefault()
            setClipboardMarkdown(event.clipboardData, markdown)
            requestFocusAfterRemovingNode(focusedComponentNode.id)
            updateNode(focusedComponentNode.id, () => null)
            return
        }
    }

    const handleNotebookPaste = (event: ReactClipboardEvent<HTMLDivElement>): void => {
        if (mode !== 'edit' || !(event.target instanceof HTMLElement) || isNativeEditableElement(event.target)) {
            return
        }

        const targetComponentNode = getFocusedComponentNode(event.target, documentRef.current.nodes, blockRefs.current)
        if (!targetComponentNode) {
            return
        }

        const pastedMarkdown = getClipboardMarkdown(event.clipboardData)
        if (!pastedMarkdown) {
            return
        }

        const didPaste = insertMarkdownAfterNode(
            targetComponentNode.id,
            pastedMarkdown,
            `component-paste-${targetComponentNode.id}-${pastedMarkdown.length}`
        )
        if (!didPaste) {
            return
        }

        event.preventDefault()
        event.stopPropagation()
    }

    const handleDebugMarkdownChange = (event: ReactChangeEvent<HTMLTextAreaElement>): void => {
        pendingDebugSelectionRef.current = {
            start: event.currentTarget.selectionStart,
            end: event.currentTarget.selectionEnd,
            direction: event.currentTarget.selectionDirection,
        }
        const nextMarkdown = event.currentTarget.value
        const nextDocument = parseMarkdownNotebook(nextMarkdown)
        const reconciledDocument = ensureEditableNotebookDocument(
            reconcileNotebookDocuments(documentRef.current, nextDocument).document
        )
        const serialized = serializeMarkdownNotebook(reconciledDocument)

        documentRef.current = reconciledDocument
        lastSerializedValueRef.current = serialized
        lastBaseValueRef.current = serialized
        setDebugMarkdown(nextMarkdown)
        setDocument(reconciledDocument)
        onChange?.(serialized)
    }

    const getCurrentSelectionInlineRanges = (): {
        textRanges: FloatingToolbarTextRange[]
        listItemRanges: FloatingToolbarListItemRange[]
    } => {
        const notebookElement = notebookRef.current
        const selection = window.getSelection()
        if (!notebookElement || !selection || selection.rangeCount === 0) {
            return { textRanges: [], listItemRanges: [] }
        }

        const range = selection.getRangeAt(0)
        if (!rangeIntersectsNode(range, notebookElement)) {
            return { textRanges: [], listItemRanges: [] }
        }

        const nodes = documentRef.current.nodes.length ? documentRef.current.nodes : [emptyNodeRef.current]
        return {
            textRanges: getSelectedTextRanges(selection, nodes, blockRefs.current),
            listItemRanges: getSelectedListItemRanges(selection, nodes, listItemRefs.current),
        }
    }

    const updateInlineSelections = (
        activeTextRanges: FloatingToolbarTextRange[] | null | undefined,
        activeListItemRanges: FloatingToolbarListItemRange[] | null | undefined,
        updater: (children: NotebookInlineNode[], range: NotebookTextSelectionRange) => NotebookInlineNode[]
    ): boolean => {
        if (!activeTextRanges?.length && !activeListItemRanges?.length) {
            return false
        }

        const rangesByNodeId = new Map(activeTextRanges?.map(({ range }) => [range.nodeId, range]) ?? [])
        const listItemRangesByNodeId = new Map<string, FloatingToolbarListItemRange[]>()
        activeListItemRanges?.forEach((listItemRange) => {
            listItemRangesByNodeId.set(listItemRange.node.id, [
                ...(listItemRangesByNodeId.get(listItemRange.node.id) ?? []),
                listItemRange,
            ])
        })
        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]

        // Restore targets must be in document order: the first and last entries bound the selection.
        restoreSelectionRef.current = {
            textRanges: nodes.flatMap((node): RestoreTextRange[] => {
                const textRange = rangesByNodeId.get(node.id)
                if (textRange) {
                    return [textRange]
                }
                return (listItemRangesByNodeId.get(node.id) ?? []).map(({ range, itemIndex }) => ({
                    ...range,
                    listItemIndex: itemIndex,
                }))
            }),
        }
        commitDocument({
            ...currentDocument,
            nodes: nodes.map((node) => {
                const range = rangesByNodeId.get(node.id)
                if (range && isTextBlockNode(node)) {
                    return {
                        ...node,
                        children: updater(node.children, range),
                    }
                }

                const listItemRanges = listItemRangesByNodeId.get(node.id)
                if (listItemRanges?.length && node.type === 'list') {
                    const rangesByItemIndex = new Map(listItemRanges.map((entry) => [entry.itemIndex, entry.range]))
                    return {
                        ...node,
                        items: node.items.map((item, itemIndex) => {
                            const itemRange = rangesByItemIndex.get(itemIndex)
                            if (!itemRange) {
                                return item
                            }
                            return { ...item, children: updater(item.children, itemRange) }
                        }),
                    }
                }

                return node
            }),
        })
        return true
    }

    const applyInlineMark = (
        markType: NotebookInlineMark['type'],
        activeRanges: {
            textRanges: FloatingToolbarTextRange[] | null | undefined
            listItemRanges: FloatingToolbarListItemRange[] | null | undefined
        } = { textRanges: floatingToolbar?.textRanges, listItemRanges: floatingToolbar?.listItemRanges }
    ): boolean => {
        const activeTextRanges = activeRanges.textRanges ?? []
        const activeListItemRanges = activeRanges.listItemRanges ?? []
        if (!activeTextRanges.length && !activeListItemRanges.length) {
            return false
        }

        if (floatingToolbar) {
            floatingToolbarPositionLockRef.current = {
                placement: floatingToolbar.placement,
                top: floatingToolbar.top,
                left: floatingToolbar.left,
            }
        }

        const currentNodes = documentRef.current.nodes.length ? documentRef.current.nodes : [emptyNodeRef.current]
        const currentNodesById = new Map(currentNodes.map((node) => [node.id, node]))
        const currentTextRanges = activeTextRanges.map(({ node, range }) => {
            const currentNode = currentNodesById.get(node.id)
            return {
                node: currentNode && isTextBlockNode(currentNode) ? currentNode : node,
                range,
            }
        })
        const currentListItemRanges = activeListItemRanges.map((listItemRange) => {
            const currentNode = currentNodesById.get(listItemRange.node.id)
            return {
                ...listItemRange,
                node: currentNode?.type === 'list' ? currentNode : listItemRange.node,
            }
        })
        const markSelections: InlineMarkSelection[] = [
            ...currentTextRanges.map(({ node, range }) => ({ children: node.children, range })),
            ...currentListItemRanges.map(({ node, itemIndex, range }) => ({
                children: node.items[itemIndex]?.children ?? [],
                range,
            })),
        ]
        const shouldApplyMark = !areInlineSelectionsFullyMarked(markSelections, markType)

        return updateInlineSelections(currentTextRanges, currentListItemRanges, (children, range) =>
            setInlineMark(children, range, markType, shouldApplyMark)
        )
    }

    const applyInlineLink = (href: string | null): void => {
        updateInlineSelections(floatingToolbar?.textRanges, floatingToolbar?.listItemRanges, (children, range) =>
            setInlineLinkMark(children, range, href)
        )
        floatingToolbarPositionLockRef.current = null
        setFloatingToolbar(null)
    }

    const setSelectedBlockStyle = (style: TextBlockStyle): void => {
        const activeTextRanges = floatingToolbar?.textRanges
        const activeCodeRanges = floatingToolbar?.codeRanges
        const activeListItemRanges = floatingToolbar?.listItemRanges
        if (!activeTextRanges?.length && !activeCodeRanges?.length && !activeListItemRanges?.length) {
            return
        }

        const selectedTextNodeIds = new Set(activeTextRanges?.map(({ node }) => node.id) ?? [])
        const selectedCodeNodeIds = new Set(activeCodeRanges?.map(({ node }) => node.id) ?? [])
        const selectedListNodeIds = new Set(activeListItemRanges?.map(({ node }) => node.id) ?? [])
        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]

        const inlineRangesByNodeId = new Map(
            [...(activeTextRanges ?? []), ...(activeCodeRanges ?? [])].map(({ range }) => [range.nodeId, range])
        )
        const listItemRangesByNodeId = new Map<string, FloatingToolbarListItemRange[]>()
        activeListItemRanges?.forEach((listItemRange) => {
            listItemRangesByNodeId.set(listItemRange.node.id, [
                ...(listItemRangesByNodeId.get(listItemRange.node.id) ?? []),
                listItemRange,
            ])
        })
        restoreSelectionRef.current = {
            textRanges: nodes.flatMap((node): RestoreTextRange[] => {
                const inlineRange = inlineRangesByNodeId.get(node.id)
                if (inlineRange) {
                    return [inlineRange]
                }
                return (listItemRangesByNodeId.get(node.id) ?? []).map(({ range, itemIndex }) => ({
                    ...range,
                    listItemIndex: itemIndex,
                }))
            }),
        }
        commitDocument({
            ...currentDocument,
            nodes: nodes.map((node) => {
                if (selectedCodeNodeIds.has(node.id) && node.type === 'code') {
                    if (style === 'code') {
                        return node
                    }
                    const children = plainTextToInlineNodes(node.text)
                    if (typeof style === 'number') {
                        return { id: node.id, type: 'heading', level: style, children }
                    }
                    return { id: node.id, type: style, children }
                }
                if (selectedListNodeIds.has(node.id) && node.type === 'list') {
                    // Lists only toggle blockquote membership; heading and code styles do not apply to them.
                    if (style === 'blockquote' && !node.blockquote) {
                        return { ...node, blockquote: true }
                    }
                    if (style === 'paragraph' && node.blockquote) {
                        return { ...node, blockquote: undefined }
                    }
                    return node
                }
                if (!selectedTextNodeIds.has(node.id) || !isTextBlockNode(node)) {
                    return node
                }

                if (style === 'code') {
                    return {
                        id: node.id,
                        type: 'code',
                        text: getInlineText(node.children),
                    }
                }
                if (typeof style === 'number') {
                    return { ...node, type: 'heading', level: style }
                }
                return { ...node, type: style, level: undefined }
            }),
        })
    }

    const askAIAboutSelection = (): void => {
        if (!floatingToolbar || !onAskAI) {
            return
        }

        const selectedMarkdown = floatingToolbar.selectedMarkdown
        if (!selectedMarkdown.trim()) {
            return
        }

        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
        // Insert the prompt after the last selected block in document order.
        const selectedNodeIds = new Set(
            [
                ...floatingToolbar.textRanges.map(({ node }) => node.id),
                ...floatingToolbar.listItemRanges.map(({ node }) => node.id),
            ].filter(Boolean)
        )
        const targetNodeIndex = nodes.reduce(
            (lastIndex, node, index) => (selectedNodeIds.has(node.id) ? index : lastIndex),
            -1
        )
        if (targetNodeIndex < 0) {
            return
        }
        const targetNodeId = nodes[targetNodeIndex].id

        const promptNode: NotebookComponentBlockNode = {
            id: makeEmptyParagraph(`ai-selection-${targetNodeId}`).id,
            type: 'component',
            tagName: 'Prompt',
            props: {
                question: '',
                source: 'selection',
                selectedMarkdown,
            },
        }
        onInteractionStateChange?.(true)
        commitDocument({
            ...currentDocument,
            nodes: nodes.flatMap((node, index) => (index === targetNodeIndex ? [node, promptNode] : [node])),
        })

        floatingToolbarPositionLockRef.current = null
        setFloatingToolbar(null)
        setInsertMenu({
            nodeId: promptNode.id,
            query: '',
            selectedIndex: 0,
            mode: 'ai',
            source: 'selection',
            selectedMarkdown,
        })
    }

    const copyFloatingToolbarSelection = (): void => {
        if (!floatingToolbar?.selectedMarkdown) {
            return
        }

        copyMarkdownToNotebookClipboard(floatingToolbar.selectedMarkdown)
    }

    const openInsertMenu = (nodeId: string, query: string = ''): void => {
        onInteractionStateChange?.(true)
        setInsertMenu((currentMenu) => ({
            nodeId,
            query,
            selectedIndex: 0,
            mode: 'tools',
            detached: currentMenu?.nodeId === nodeId ? currentMenu.detached : undefined,
            removeNodeOnClose: currentMenu?.nodeId === nodeId ? currentMenu.removeNodeOnClose : undefined,
        }))
    }

    const openDetachedInsertMenuFromNode = useCallback(
        (nodeId: string, query: string = ''): boolean => {
            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const nodeIndex = nodes.findIndex((node) => node.id === nodeId)
            const node = nodes[nodeIndex]
            if (nodeIndex <= 0 || !node || !isTextBlockNode(node)) {
                return false
            }

            const commandNode = makeEmptyParagraph(`slash-command-${node.id}`)
            commandNode.children = query ? [{ type: 'text', text: query }] : []
            restoreSelectionRef.current = { nodeId: commandNode.id, start: query.length, end: query.length }
            onInteractionStateChange?.(true)
            setInsertMenu({ nodeId: commandNode.id, query, selectedIndex: 0, mode: 'tools', detached: true })
            commitDocument({
                ...currentDocument,
                nodes: nodes.map((currentNode) => (currentNode.id === node.id ? commandNode : currentNode)),
            })
            return true
        },
        [commitDocument, onInteractionStateChange]
    )

    const clearInsertMenu = useCallback((): void => {
        setInsertMenu(null)
    }, [])

    const removeTemporaryInsertMenuNode = useCallback(
        (menu: InsertMenuState | null): void => {
            if (!menu?.removeNodeOnClose) {
                return
            }

            const currentDocument = documentRef.current
            const nodeIndex = currentDocument.nodes.findIndex((node) => node.id === menu.nodeId)
            const node = currentDocument.nodes[nodeIndex]
            if (!node || !isTextBlockNode(node)) {
                return
            }

            delete blockRefs.current[menu.nodeId]
            commitDocument(
                {
                    ...currentDocument,
                    nodes: currentDocument.nodes.filter((_, index) => index !== nodeIndex),
                },
                { addToHistory: false }
            )
        },
        [commitDocument]
    )

    const dismissInsertMenu = useCallback((): void => {
        removeTemporaryInsertMenuNode(insertMenu)
        setInsertMenu(null)
    }, [insertMenu, removeTemporaryInsertMenuNode])

    const updateInsertMenuPosition = useCallback((): void => {
        if (!insertMenu) {
            setInsertMenuPosition(null)
            return
        }

        const anchorElement = blockRefs.current[insertMenu.nodeId]
        if (!anchorElement) {
            setInsertMenuPosition(null)
            return
        }

        setInsertMenuPosition(getInsertMenuPosition(anchorElement))
    }, [insertMenu])

    useLayoutEffect(() => {
        updateInsertMenuPosition()
    }, [document, insertMenu, updateInsertMenuPosition])

    useEffect(() => {
        if (!insertMenu) {
            setInsertMenuPosition(null)
            return
        }

        window.addEventListener('resize', updateInsertMenuPosition)
        window.addEventListener('scroll', updateInsertMenuPosition, true)

        return () => {
            window.removeEventListener('resize', updateInsertMenuPosition)
            window.removeEventListener('scroll', updateInsertMenuPosition, true)
        }
    }, [insertMenu, updateInsertMenuPosition])

    useEffect(() => {
        if (!insertMenu) {
            return
        }

        const closeInsertMenuOnOutsidePointerDown = (event: PointerEvent): void => {
            const target = event.target
            if (!(target instanceof Node)) {
                return
            }

            const activeBlockElement = blockRefs.current[insertMenu.nodeId]
            const activeRowElement = activeBlockElement?.closest('.MarkdownNotebook__row')
            if (activeRowElement?.contains(target)) {
                return
            }

            dismissInsertMenu()
        }

        window.document.addEventListener('pointerdown', closeInsertMenuOnOutsidePointerDown)

        return () => {
            window.document.removeEventListener('pointerdown', closeInsertMenuOnOutsidePointerDown)
        }
    }, [dismissInsertMenu, insertMenu])

    const openInsertMenuAtBoundary = (boundaryIndex: number): void => {
        if (boundaryIndex <= 0) {
            return
        }

        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes
        const insertedNode = makeEmptyParagraph(`boundary-${String(boundaryIndex)}`)
        const clampedBoundaryIndex = Math.max(1, Math.min(boundaryIndex, nodes.length))

        commitDocument({
            ...currentDocument,
            nodes: [...nodes.slice(0, clampedBoundaryIndex), insertedNode, ...nodes.slice(clampedBoundaryIndex)],
        })
        restoreSelectionRef.current = { nodeId: insertedNode.id, start: 0, end: 0 }
        onInteractionStateChange?.(true)
        setInsertMenu({
            nodeId: insertedNode.id,
            query: '',
            selectedIndex: 0,
            mode: 'tools',
            detached: true,
            removeNodeOnClose: true,
        })
    }

    const insertEmptyParagraphAfterNode = useCallback(
        (nodeId: string): void => {
            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const nodeIndex = nodes.findIndex((node) => node.id === nodeId)
            if (nodeIndex === -1) {
                return
            }

            const nextNode = nodes[nodeIndex + 1]
            if (isBlankInsertMenuButtonRow(nextNode)) {
                const nextElement = blockRefs.current[nextNode.id]
                if (nextElement) {
                    nextElement.focus()
                    restoreSelection(nextElement, 0, 0)
                    return
                }
                restoreSelectionRef.current = { nodeId: nextNode.id, start: 0, end: 0 }
                return
            }

            const insertedNode = makeEmptyParagraph(`after-${nodeId}`)
            commitDocument({
                ...currentDocument,
                nodes: [...nodes.slice(0, nodeIndex + 1), insertedNode, ...nodes.slice(nodeIndex + 1)],
            })
            restoreSelectionRef.current = { nodeId: insertedNode.id, start: 0, end: 0 }
        },
        [commitDocument]
    )

    const focusLowestNotebookRow = useCallback((): boolean => {
        const nodes = documentRef.current.nodes.length ? documentRef.current.nodes : [emptyNodeRef.current]
        for (let nodeIndex = nodes.length - 1; nodeIndex >= 0; nodeIndex--) {
            const node = nodes[nodeIndex]

            if (isTextBlockNode(node)) {
                const element = blockRefs.current[node.id]
                if (!element) {
                    continue
                }

                const targetOffset = getInlineText(node.children).length
                element.focus()
                restoreSelection(element, targetOffset, targetOffset)
                return true
            }

            if (node.type === 'list') {
                const itemIndex = node.items.length - 1
                if (itemIndex < 0) {
                    continue
                }

                const element = listItemRefs.current[getListItemRefKey(node.id, itemIndex)]
                if (!element) {
                    continue
                }

                const targetOffset = getInlineText(node.items[itemIndex].children).length
                element.focus()
                restoreSelection(element, targetOffset, targetOffset)
                return true
            }

            if (node.type === 'table') {
                const position = getTableEdgeCellPosition(node, 'previous')
                const element = position ? tableCellRefs.current[getTableCellRefKey(node.id, position)] : null
                if (!position || !element) {
                    continue
                }

                const targetOffset = getInlineText(getTableCellAtPosition(node, position)?.children ?? []).length
                element.focus()
                restoreSelection(element, targetOffset, targetOffset)
                return true
            }

            if (node.type === 'component') {
                const element = blockRefs.current[node.id]
                if (!element) {
                    continue
                }

                element.focus()
                return true
            }
        }

        return false
    }, [insertMenu])

    const requestFocusForNode = useCallback((node: NotebookBlockNode, placement: 'start' | 'end'): boolean => {
        const offsetForChildren = (children: NotebookInlineNode[]): number =>
            placement === 'start' ? 0 : getInlineText(children).length

        if (isTextBlockNode(node)) {
            const offset = offsetForChildren(node.children)
            restoreSelectionRef.current = { nodeId: node.id, start: offset, end: offset }
            return true
        }

        if (node.type === 'component') {
            focusNodeRef.current = node.id
            return true
        }

        if (node.type === 'list' && node.items.length) {
            const listItemIndex = placement === 'start' ? 0 : node.items.length - 1
            const offset = offsetForChildren(node.items[listItemIndex].children)
            restoreSelectionRef.current = {
                nodeId: node.id,
                listItemIndex,
                listItemId: node.items[listItemIndex].id,
                start: offset,
                end: offset,
            }
            return true
        }

        if (node.type === 'table') {
            const tableCell = getTableEdgeCellPosition(node, placement === 'start' ? 'next' : 'previous')
            if (!tableCell) {
                return false
            }

            const offset = offsetForChildren(getTableCellAtPosition(node, tableCell)?.children ?? [])
            restoreSelectionRef.current = { nodeId: node.id, tableCell, start: offset, end: offset }
            return true
        }

        return false
    }, [])

    const requestFocusAfterRemovingNode = useCallback(
        (nodeId: string): void => {
            const nodes = documentRef.current.nodes.length ? documentRef.current.nodes : [emptyNodeRef.current]
            const nodeIndex = nodes.findIndex((node) => node.id === nodeId)
            if (nodeIndex === -1) {
                return
            }

            const nextNode = nodes[nodeIndex + 1]
            if (nextNode && requestFocusForNode(nextNode, 'start')) {
                return
            }

            const previousNode = nodes[nodeIndex - 1]
            if (previousNode && requestFocusForNode(previousNode, 'end')) {
                return
            }

            restoreSelectionRef.current = { nodeId: emptyNodeRef.current.id, start: 0, end: 0 }
        },
        [requestFocusForNode]
    )

    const deleteEmptyCodeBlockAtCurrentSelection = useCallback((): boolean => {
        const element = getSelectedInlineEditableElementOfType(notebookRef.current, 'MarkdownNotebook__code-block')
        const nodeId = element?.dataset.markdownNotebookNodeId
        if (!element || !nodeId) {
            return false
        }

        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
        const node = nodes.find((currentNode) => currentNode.id === nodeId)
        if (!node || node.type !== 'code' || node.text.length) {
            return false
        }

        requestFocusAfterRemovingNode(nodeId)
        commitDocument({
            ...currentDocument,
            nodes: nodes.filter((currentNode) => currentNode.id !== nodeId),
        })
        return true
    }, [commitDocument, requestFocusAfterRemovingNode])

    const deleteNodeAndFocusPrevious = useCallback(
        (nodeId: string): boolean => {
            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const nodeIndex = nodes.findIndex((node) => node.id === nodeId)
            if (nodeIndex <= 0) {
                return false
            }

            const previousNode = nodes[nodeIndex - 1]
            if (!previousNode || !requestFocusForNode(previousNode, 'end')) {
                return false
            }

            commitDocument({
                ...currentDocument,
                nodes: nodes.filter((_, index) => index !== nodeIndex),
            })
            return true
        },
        [commitDocument, requestFocusForNode]
    )

    const focusPreviousNodeAtBoundaryEnd = useCallback(
        (boundaryIndex: number): void => {
            const nodes = documentRef.current.nodes.length ? documentRef.current.nodes : [emptyNodeRef.current]
            const previousNode = nodes[boundaryIndex - 1]
            if (!previousNode) {
                return
            }

            if (isTextBlockNode(previousNode)) {
                const element = blockRefs.current[previousNode.id]
                if (!element) {
                    return
                }

                const endOffset = getInlineText(previousNode.children).length
                element.focus()
                restoreSelection(element, endOffset, endOffset)
                return
            }

            requestFocusForNode(previousNode, 'end')
        },
        [requestFocusForNode]
    )

    const moveFocusToAdjacentNode = useCallback(
        (nodeId: string, direction: InsertMenuSelectionDirection, offset: number): boolean => {
            const nodes = documentRef.current.nodes.length ? documentRef.current.nodes : [emptyNodeRef.current]
            const nodeIndex = nodes.findIndex((node) => node.id === nodeId)
            if (nodeIndex === -1) {
                return false
            }

            const step = direction === 'next' ? 1 : -1
            let targetIndex = nodeIndex + step
            while (targetIndex >= 0 && targetIndex < nodes.length) {
                const targetNode = nodes[targetIndex]
                if (isTextBlockNode(targetNode)) {
                    const element = blockRefs.current[targetNode.id]
                    if (!element) {
                        return false
                    }

                    const targetOffset = Math.min(offset, getInlineText(targetNode.children).length)
                    element.focus()
                    restoreSelection(element, targetOffset, targetOffset)
                    return true
                }

                if (targetNode.type === 'component') {
                    const element = blockRefs.current[targetNode.id]
                    if (!element) {
                        return false
                    }

                    element.focus()
                    return true
                }

                if (targetNode.type === 'list') {
                    const targetItemIndex = direction === 'next' ? 0 : targetNode.items.length - 1
                    const element = listItemRefs.current[getListItemRefKey(targetNode.id, targetItemIndex)]
                    if (!element) {
                        return false
                    }

                    const targetOffset = Math.min(
                        offset,
                        getInlineText(targetNode.items[targetItemIndex].children).length
                    )
                    element.focus()
                    restoreSelection(element, targetOffset, targetOffset)
                    return true
                }

                if (targetNode.type === 'table') {
                    const targetCellPosition = getTableEdgeCellPosition(targetNode, direction)
                    if (!targetCellPosition) {
                        return false
                    }

                    const element = tableCellRefs.current[getTableCellRefKey(targetNode.id, targetCellPosition)]
                    if (!element) {
                        return false
                    }

                    const targetOffset = Math.min(
                        offset,
                        getInlineText(getTableCellAtPosition(targetNode, targetCellPosition)?.children ?? []).length
                    )
                    element.focus()
                    restoreSelection(element, targetOffset, targetOffset)
                    return true
                }

                targetIndex += step
            }

            return false
        },
        [insertMenu]
    )

    const moveFocusToAdjacentTableCell = useCallback(
        (
            nodeId: string,
            position: TableCellPosition,
            direction: InsertMenuSelectionDirection,
            offset: number
        ): boolean => {
            const nodes = documentRef.current.nodes.length ? documentRef.current.nodes : [emptyNodeRef.current]
            const node = nodes.find(
                (candidate): candidate is NotebookTableBlockNode =>
                    candidate.id === nodeId && candidate.type === 'table'
            )
            if (!node) {
                return false
            }

            const positions = getTableCellPositions(node)
            const currentIndex = positions.findIndex((candidate) => tableCellPositionsEqual(candidate, position))
            if (currentIndex === -1) {
                return false
            }

            const nextPosition = positions[currentIndex + (direction === 'next' ? 1 : -1)]
            if (!nextPosition) {
                return moveFocusToAdjacentNode(nodeId, direction, offset)
            }

            const element = tableCellRefs.current[getTableCellRefKey(nodeId, nextPosition)]
            if (!element) {
                return false
            }

            const targetOffset = Math.min(
                offset,
                getInlineText(getTableCellAtPosition(node, nextPosition)?.children ?? []).length
            )
            element.focus()
            restoreSelection(element, targetOffset, targetOffset)
            return true
        },
        [moveFocusToAdjacentNode]
    )

    const moveTableCellFocusAtCurrentSelection = useCallback(
        (direction: InsertMenuSelectionDirection): boolean => {
            const element = getSelectedInlineEditableElementOfType(
                notebookRef.current,
                'MarkdownNotebook__table-cell-content'
            )
            const position = element ? getTableCellPositionFromElement(element) : null
            const nodeId = element?.dataset.markdownNotebookNodeId
            if (!element || !position || !nodeId) {
                return false
            }

            const offset = getCollapsedSelectionRange(element, nodeId)?.start ?? 0
            moveFocusToAdjacentTableCell(nodeId, position, direction, offset)
            return true
        },
        [moveFocusToAdjacentTableCell]
    )

    const indentCodeBlockAtCurrentSelection = useCallback((): boolean => {
        const element = getSelectedInlineEditableElementOfType(notebookRef.current, 'MarkdownNotebook__code-block')
        const nodeId = element?.dataset.markdownNotebookNodeId
        if (!element || !nodeId) {
            return false
        }

        window.document.execCommand('insertText', false, '    ')
        updateNode(nodeId, (currentNode) => {
            if (currentNode.type !== 'code') {
                return currentNode
            }
            return { ...currentNode, text: element.textContent ?? '' }
        })
        return true
    }, [updateNode])

    const selectNotebookContents = (): boolean => {
        const canvasElement = canvasRef.current
        const selection = window.getSelection()
        if (!canvasElement || !selection) {
            return false
        }

        const nodes = documentRef.current.nodes.length ? documentRef.current.nodes : [emptyNodeRef.current]
        const firstNode = nodes.find((node) => blockRefs.current[node.id])
        const lastNode = [...nodes].reverse().find((node) => blockRefs.current[node.id])
        if (!firstNode || !lastNode) {
            return false
        }

        const firstElement = blockRefs.current[firstNode.id]
        const lastElement = blockRefs.current[lastNode.id]
        if (!firstElement || !lastElement) {
            return false
        }

        const range = canvasElement.ownerDocument.createRange()
        setNotebookSelectionStart(range, firstNode, firstElement)
        setNotebookSelectionEnd(range, lastNode, lastElement)
        selection.removeAllRanges()
        selection.addRange(range)

        setSelectedComponentNodeIds(getSelectedComponentNodeIds(selection, nodes, blockRefs.current))
        scheduleFloatingToolbarUpdateFromSelection()
        return true
    }

    const selectTextBlockContents = (target: EventTarget | null): boolean => {
        if (!(target instanceof HTMLElement)) {
            return false
        }

        const activeTextBlockElement = target.closest('.MarkdownNotebook__text-block')
        const selection = window.getSelection()
        if (!(activeTextBlockElement instanceof HTMLElement) || !canvasRef.current?.contains(activeTextBlockElement)) {
            return false
        }

        if (!selection) {
            return false
        }

        const range = activeTextBlockElement.ownerDocument.createRange()
        const startPosition = findTextPosition(activeTextBlockElement, 0)
        const endPosition = findTextPosition(activeTextBlockElement, activeTextBlockElement.textContent?.length ?? 0)
        range.setStart(startPosition.node, startPosition.offset)
        range.setEnd(endPosition.node, endPosition.offset)
        if (selectionMatchesRange(selection, range)) {
            return false
        }

        selection.removeAllRanges()
        selection.addRange(range)

        setSelectedComponentNodeIds(new Set())
        scheduleFloatingToolbarUpdateFromSelection()
        return true
    }

    const selectCodeBlockContents = (target: EventTarget | null): boolean => {
        if (!(target instanceof HTMLElement)) {
            return false
        }

        const codeBlockElement = target.closest('.MarkdownNotebook__code-block')
        if (!(codeBlockElement instanceof HTMLElement) || !canvasRef.current?.contains(codeBlockElement)) {
            return false
        }

        const selection = window.getSelection()
        if (!selection) {
            return false
        }

        const range = codeBlockElement.ownerDocument.createRange()
        const startPosition = findTextPosition(codeBlockElement, 0)
        const endPosition = findTextPosition(codeBlockElement, codeBlockElement.textContent?.length ?? 0)
        range.setStart(startPosition.node, startPosition.offset)
        range.setEnd(endPosition.node, endPosition.offset)
        if (selectionMatchesRange(selection, range)) {
            return false
        }

        codeBlockElement.focus()
        selection.removeAllRanges()
        selection.addRange(range)
        setSelectedComponentNodeIds(new Set())
        scheduleFloatingToolbarUpdateFromSelection()
        return true
    }

    const selectAIPromptContents = (target: EventTarget | null): boolean => {
        if (!(target instanceof HTMLElement)) {
            return false
        }

        const aiPromptTextBlock = target.closest('.MarkdownNotebook__text-block--ai-prompt')
        if (!(aiPromptTextBlock instanceof HTMLElement) || !canvasRef.current?.contains(aiPromptTextBlock)) {
            return false
        }

        aiPromptTextBlock.focus()
        restoreSelection(aiPromptTextBlock, 0, aiPromptTextBlock.textContent?.length ?? 0)
        scheduleFloatingToolbarUpdateFromSelection()
        return true
    }

    const handleNotebookKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
        if (mode !== 'edit' || event.altKey || !(event.metaKey || event.ctrlKey)) {
            return
        }

        if (
            event.target instanceof HTMLElement &&
            (event.target.closest('.MarkdownNotebook__debug-drawer') || isNativeEditableElement(event.target))
        ) {
            return
        }

        const key = event.key.toLowerCase()
        const inlineMarkShortcuts: Partial<Record<string, NotebookInlineMark['type']>> = {
            b: 'bold',
            i: 'italic',
            u: 'underline',
        }

        if (!event.shiftKey && key === 'a') {
            if (selectAIPromptContents(event.target)) {
                event.preventDefault()
                event.stopPropagation()
                return
            }

            if (insertMenu) {
                return
            }

            if (selectTextBlockContents(event.target) || selectCodeBlockContents(event.target)) {
                event.preventDefault()
                event.stopPropagation()
                return
            }

            if (selectNotebookContents()) {
                event.preventDefault()
                event.stopPropagation()
            }
            return
        }

        const inlineMarkType = event.shiftKey ? null : inlineMarkShortcuts[key]
        if (inlineMarkType) {
            if (insertMenu) {
                return
            }

            if (applyInlineMark(inlineMarkType, getCurrentSelectionInlineRanges())) {
                event.preventDefault()
                event.stopPropagation()
            }
            return
        }

        const focusedComponentNode = getFocusedComponentNode(
            window.document.activeElement,
            documentRef.current.nodes,
            blockRefs.current
        )
        if (focusedComponentNode && !event.shiftKey && key === 'c') {
            const focusedComponentElement = blockRefs.current[focusedComponentNode.id]
            if (focusedComponentElement && isSelectionInsideElement(window.getSelection(), focusedComponentElement)) {
                return
            }

            copyMarkdownToNotebookClipboard(serializeNotebookNodes([focusedComponentNode]))
            event.preventDefault()
            event.stopPropagation()
            return
        }
        if (focusedComponentNode && !event.shiftKey && key === 'v') {
            pasteNotebookClipboardAfterNode(focusedComponentNode.id)
            event.preventDefault()
            event.stopPropagation()
            return
        }

        const isUndoShortcut = key === 'z'
        const isRedoShortcut = key === 'y' && !event.shiftKey
        if (!isUndoShortcut && !isRedoShortcut) {
            return
        }

        if (isUndoShortcut) {
            if (event.shiftKey) {
                redoHistory()
            } else {
                undoHistory()
            }
        } else {
            redoHistory()
        }

        event.preventDefault()
        event.stopPropagation()
    }

    const handleMainMouseDown = (event: ReactMouseEvent<HTMLDivElement>): void => {
        if (mode !== 'edit' || event.button !== 0 || event.defaultPrevented) {
            return
        }

        if (!(event.target instanceof HTMLElement)) {
            return
        }

        if (
            event.target.closest(
                '.MarkdownNotebook__row, .MarkdownNotebook__insert-boundary, .MarkdownNotebook__debug-toolbar, .MarkdownNotebook__debug-drawer, .MarkdownNotebook__insert-menu, .MarkdownNotebook__format-toolbar, button, a, input, textarea, select, [role="button"], [contenteditable="true"]'
            )
        ) {
            return
        }

        const canvasElement = canvasRef.current
        const clickedInsideCanvas = canvasElement?.contains(event.target) ?? false
        const clickedBelowCanvas = canvasElement ? event.clientY >= canvasElement.getBoundingClientRect().bottom : true
        if (!clickedInsideCanvas && !clickedBelowCanvas) {
            return
        }

        if (focusLowestNotebookRow()) {
            event.preventDefault()
        }
    }

    const updateActiveBoundaryFromRow = (event: ReactMouseEvent<HTMLElement>, rowIndex: number): void => {
        setActiveRowIndex(rowIndex)

        if (focusedRowIndex !== null || insertMenu) {
            setActiveBoundaryIndex(null)
            return
        }

        setActiveBoundaryIndex(getClosestInsertBoundaryIndex(event.currentTarget, rowIndex, event.clientY))
    }

    const handleRowFocus = (rowIndex: number): void => {
        setActiveRowIndex(rowIndex)
        setActiveBoundaryIndex(null)
        setFocusedRowIndex(rowIndex)
    }

    const handleRowBlur = (event: ReactFocusEvent<HTMLDivElement>, rowIndex: number): void => {
        const nextTarget = event.relatedTarget
        if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) {
            return
        }

        setFocusedRowIndex((currentRowIndex) => (currentRowIndex === rowIndex ? null : currentRowIndex))
    }

    const handleCanvasMouseLeave = (): void => {
        setActiveRowIndex(null)
        setActiveBoundaryIndex(null)
    }

    const handleRootEditableInput = (event: FormEvent<HTMLDivElement>): void => {
        if (event.target !== event.currentTarget) {
            return
        }

        const inlineEditableElement = getInlineEditableElementForSelection(window.getSelection(), event.currentTarget)
        if (!inlineEditableElement) {
            return
        }

        const nodeId = inlineEditableElement.dataset.markdownNotebookNodeId
        if (!nodeId) {
            return
        }
        const nodes = documentRef.current.nodes.length ? documentRef.current.nodes : [emptyNodeRef.current]

        if (inlineEditableElement.classList.contains('MarkdownNotebook__code-block')) {
            updateNode(nodeId, (currentNode) => {
                if (currentNode.type !== 'code') {
                    return currentNode
                }
                return { ...currentNode, text: inlineEditableElement.textContent ?? '' }
            })
            return
        }

        const nextChildren = htmlElementToInlineNodes(inlineEditableElement)
        if (inlineEditableElement.classList.contains('MarkdownNotebook__text-block')) {
            const nodeIndex = nodes.findIndex((node) => node.id === nodeId)
            const node = nodes[nodeIndex]
            const nextText = getInlineText(nextChildren)
            const slashQuery = getSlashCommandQuery(nextText)
            if (node && isPromptComponentNode(node)) {
                rootEditableInputHtmlByNodeIdRef.current[nodeId] = inlineNodesToHtml(nextChildren)
                if (getNotebookStringProp(node.props.question) !== nextText) {
                    updateNode(nodeId, (currentNode) => {
                        if (!isPromptComponentNode(currentNode)) {
                            return currentNode
                        }
                        return {
                            ...currentNode,
                            props: {
                                ...currentNode.props,
                                question: nextText,
                            },
                        }
                    })
                }
                updateAIPromptQuery(nodeId, nextText)
                return
            }
            if (node && isTextBlockNode(node)) {
                const shortcutReplacement = getTextBlockShortcutReplacement(node, nodeIndex === 0, nextText)
                if (shortcutReplacement) {
                    clearInsertMenu()
                    rootEditableInputHtmlByNodeIdRef.current[nodeId] = ''
                    replaceNodeWithNodes(nodeId, shortcutReplacement.nodes)
                    restoreSelectionRef.current = shortcutReplacement.restoreSelection
                    return
                }
            }
            if (nodeIndex > 0 && node && isTextBlockNode(node) && slashQuery !== null) {
                const queryChildren: NotebookInlineNode[] = slashQuery ? [{ type: 'text', text: slashQuery }] : []
                const nextHtml = inlineNodesToHtml(queryChildren)
                rootEditableInputHtmlByNodeIdRef.current[nodeId] = nextHtml
                if (inlineEditableElement.innerHTML !== nextHtml) {
                    inlineEditableElement.innerHTML = nextHtml
                }
                restoreSelection(
                    inlineEditableElement,
                    getInlineText(queryChildren).length,
                    getInlineText(queryChildren).length
                )
                updateNode(nodeId, (currentNode) => {
                    if (!isTextBlockNode(currentNode)) {
                        return currentNode
                    }
                    return { ...currentNode, children: queryChildren }
                })
                openInsertMenu(nodeId, slashQuery)
                return
            }

            rootEditableInputHtmlByNodeIdRef.current[nodeId] = inlineNodesToHtml(nextChildren)
            updateNode(nodeId, (currentNode) => {
                if (!isTextBlockNode(currentNode)) {
                    return currentNode
                }
                return { ...currentNode, children: nextChildren }
            })
            if (insertMenu?.nodeId === nodeId && insertMenu.mode === 'tools') {
                openInsertMenu(nodeId, nextText)
            } else if (insertMenu?.nodeId === nodeId && insertMenu.mode === 'ai') {
                updateAIPromptQuery(nodeId, nextText)
            }
            return
        }

        if (inlineEditableElement.classList.contains('MarkdownNotebook__list-item-content')) {
            const itemId = inlineEditableElement.dataset.markdownNotebookListItemId
            const itemIndex = Number(inlineEditableElement.dataset.markdownNotebookListItemIndex)
            if (!Number.isInteger(itemIndex)) {
                return
            }

            updateNode(nodeId, (currentNode) => {
                if (currentNode.type !== 'list') {
                    return currentNode
                }
                const targetItemIndex = getListItemIndex(currentNode.items, itemIndex, itemId)
                if (!currentNode.items[targetItemIndex]) {
                    return currentNode
                }
                return {
                    ...currentNode,
                    items: currentNode.items.map((item, index) =>
                        index === targetItemIndex ? { ...item, children: nextChildren } : item
                    ),
                }
            })
            return
        }

        if (inlineEditableElement.classList.contains('MarkdownNotebook__table-cell-content')) {
            const section = inlineEditableElement.dataset.markdownNotebookTableSection
            const rowIndex = Number(inlineEditableElement.dataset.markdownNotebookTableRowIndex)
            const columnIndex = Number(inlineEditableElement.dataset.markdownNotebookTableColumnIndex)
            if (
                (section !== 'header' && section !== 'body') ||
                !Number.isInteger(rowIndex) ||
                !Number.isInteger(columnIndex)
            ) {
                return
            }

            updateNode(nodeId, (currentNode) => {
                if (currentNode.type !== 'table') {
                    return currentNode
                }

                const columnCount = getTableColumnCount(currentNode)
                if (section === 'header') {
                    const nextHeaders = normalizeTableRow(currentNode.headers, columnCount)
                    nextHeaders[columnIndex] = { children: nextChildren }
                    return { ...currentNode, headers: nextHeaders }
                }

                const nextRows = currentNode.rows.map((row) => normalizeTableRow(row, columnCount))
                const nextRow = nextRows[rowIndex] ?? makeEmptyTableRow(columnCount)
                nextRow[columnIndex] = { children: nextChildren }
                nextRows[rowIndex] = nextRow
                return { ...currentNode, rows: nextRows }
            })
        }
    }

    const submitInsertMenuSelectionForNode = (nodeId: string, queryOverride?: string): boolean => {
        const isToolInsertMenuOpen =
            insertMenu?.nodeId === nodeId && (insertMenu.mode === undefined || insertMenu.mode === 'tools')
        if (!isToolInsertMenuOpen) {
            return false
        }

        const query = queryOverride ?? insertMenu.query
        const filteredCommands = getFilteredInsertCommands(insertCommands, query)
        const selectedIndex =
            query === insertMenu.query
                ? getClampedInsertMenuSelectedIndex(insertMenu.selectedIndex, filteredCommands.length)
                : 0
        const selectedCommand = filteredCommands[selectedIndex]
        if (!selectedCommand) {
            if (query.length > 0) {
                updateNode(nodeId, (currentNode) => {
                    if (!isTextBlockNode(currentNode)) {
                        return currentNode
                    }
                    return { ...currentNode, children: [] }
                })
                restoreSelectionRef.current = { nodeId, start: 0, end: 0 }
                setInsertMenu((currentMenu) => ({
                    nodeId,
                    query: '',
                    selectedIndex: 0,
                    mode: 'tools',
                    detached: currentMenu?.nodeId === nodeId ? currentMenu.detached : undefined,
                    removeNodeOnClose: currentMenu?.nodeId === nodeId ? currentMenu.removeNodeOnClose : undefined,
                }))
                return true
            }
            return false
        }

        selectedCommand.run(nodeId)
        if (selectedCommand.closeOnRun === false) {
            return true
        }
        if (selectedCommand.key.startsWith('text-')) {
            updateNode(nodeId, (currentNode) => {
                if (!isTextBlockNode(currentNode)) {
                    return currentNode
                }
                return { ...currentNode, children: [] }
            })
            restoreSelectionRef.current = { nodeId, start: 0, end: 0 }
        }
        clearInsertMenu()
        return true
    }

    const submitAIPromptForNode = (nodeId: string, queryOverride?: string): boolean => {
        const activeAIPromptMenu = insertMenu?.nodeId === nodeId && insertMenu.mode === 'ai' ? insertMenu : null
        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
        const currentPromptNode = nodes.find(
            (currentNode): currentNode is NotebookComponentBlockNode =>
                currentNode.id === nodeId && isPromptComponentNode(currentNode)
        )
        if ((!activeAIPromptMenu && !currentPromptNode) || !onAskAI) {
            return false
        }

        const query = (
            queryOverride ??
            activeAIPromptMenu?.query ??
            getNotebookStringProp(currentPromptNode?.props.question) ??
            ''
        ).trim()
        if (!query) {
            return false
        }

        const chatId = createAIChatId()
        const nextDocument: NotebookDocument = {
            ...currentDocument,
            nodes: nodes.map((currentNode): NotebookBlockNode => {
                if (currentNode.id !== nodeId || !isPromptComponentNode(currentNode)) {
                    return currentNode
                }
                return {
                    id: currentNode.id,
                    type: 'component',
                    tagName: 'Chat',
                    props: {
                        id: chatId,
                    },
                }
            }),
        }
        commitDocument(nextDocument)
        clearInsertMenu()
        const markdown = serializeMarkdownNotebook(nextDocument)
        const chatMarker = `<Chat id="${chatId}" />`
        const source = activeAIPromptMenu?.source ?? getPromptSource(currentPromptNode?.props.source)
        const selectedMarkdown =
            activeAIPromptMenu?.selectedMarkdown ?? getNotebookStringProp(currentPromptNode?.props.selectedMarkdown)
        onAskAI({
            chatId,
            query:
                source === 'selection' && selectedMarkdown
                    ? getAskAISelectionQuery(selectedMarkdown, query, chatId)
                    : query,
            source,
            chatNodeId: nodeId,
            chatMarker,
            markdown,
            markdownWithChat: markdown,
            selectedMarkdown,
        })
        return true
    }

    const submitActiveRootInsertMenu = (canvasElement: HTMLElement): boolean => {
        const inlineEditableElement = getInlineEditableElementForSelection(window.getSelection(), canvasElement)
        const nodeId = inlineEditableElement?.dataset.markdownNotebookNodeId
        if (!nodeId) {
            return false
        }

        const inputText = inlineEditableElement.textContent ?? ''
        if (inlineEditableElement.classList.contains('MarkdownNotebook__text-block--ai-prompt')) {
            return submitAIPromptForNode(nodeId, inputText)
        }

        if (insertMenu?.nodeId !== nodeId) {
            return false
        }

        if (insertMenu.mode === 'ai') {
            return submitAIPromptForNode(nodeId, inputText)
        }

        if (insertMenu.mode === undefined || insertMenu.mode === 'tools') {
            const slashQuery = getSlashCommandQuery(inputText)
            return submitInsertMenuSelectionForNode(nodeId, slashQuery ?? inputText)
        }

        return false
    }

    const moveActiveRootInsertMenuSelection = (
        canvasElement: HTMLElement,
        direction: InsertMenuSelectionDirection
    ): boolean => {
        const inlineEditableElement = getInlineEditableElementForSelection(window.getSelection(), canvasElement)
        const nodeId = inlineEditableElement?.dataset.markdownNotebookNodeId
        const isToolInsertMenuOpen =
            !!nodeId && insertMenu?.nodeId === nodeId && (insertMenu.mode === undefined || insertMenu.mode === 'tools')
        if (!isToolInsertMenuOpen) {
            return false
        }

        setInsertMenu((currentMenu) => {
            if (!currentMenu || currentMenu.nodeId !== nodeId) {
                return currentMenu
            }

            return {
                ...currentMenu,
                selectedIndex: getNextInsertMenuSelectedIndex(
                    currentMenu.selectedIndex,
                    getFilteredInsertCommands(insertCommands, currentMenu.query).length,
                    direction
                ),
            }
        })
        return true
    }

    const handleRootEditableKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
        // Keyboard editing is dispatched from the root editing host based on the current selection: in real
        // browsers key events target the canvas (nested contenteditable blocks are not separate editing hosts).
        // Events from native editable elements (e.g. the AI prompt textarea) are excluded, because the DOM
        // selection can still point at a previously focused block.
        if (event.target instanceof HTMLElement && isNativeEditableElement(event.target)) {
            return
        }

        if (mode === 'edit' && event.key === 'Tab' && !event.altKey && !event.metaKey && !event.ctrlKey) {
            const inlineEditableElement = getInlineEditableElementForSelection(
                window.getSelection(),
                event.currentTarget
            )
            if (inlineEditableElement?.classList.contains('MarkdownNotebook__list-item-content')) {
                event.preventDefault()
                event.stopPropagation()
                shiftListItemDepthAtCurrentSelection(event.shiftKey ? 'out' : 'in')
                return
            }
            if (inlineEditableElement?.classList.contains('MarkdownNotebook__table-cell-content')) {
                event.preventDefault()
                event.stopPropagation()
                moveTableCellFocusAtCurrentSelection(event.shiftKey ? 'previous' : 'next')
                return
            }
            if (!event.shiftKey && inlineEditableElement?.classList.contains('MarkdownNotebook__code-block')) {
                event.preventDefault()
                event.stopPropagation()
                indentCodeBlockAtCurrentSelection()
                return
            }
        }

        if (
            mode === 'edit' &&
            event.key === 'Enter' &&
            !event.shiftKey &&
            !event.altKey &&
            !event.metaKey &&
            !event.ctrlKey &&
            (splitListItemAtCurrentSelection() || insertTableRowAtCurrentSelection())
        ) {
            event.preventDefault()
            event.stopPropagation()
            return
        }

        if (
            mode === 'edit' &&
            event.target === event.currentTarget &&
            (event.key === 'Backspace' || event.key === 'Delete') &&
            !event.shiftKey &&
            !event.altKey &&
            !event.metaKey &&
            !event.ctrlKey &&
            deleteSelectedNotebookBlocks()
        ) {
            event.preventDefault()
            event.stopPropagation()
            return
        }

        if (
            mode === 'edit' &&
            (event.key === 'Backspace' || event.key === 'Delete') &&
            !event.shiftKey &&
            !event.altKey &&
            !event.metaKey &&
            !event.ctrlKey &&
            (deleteListItemAtCurrentSelection(event.key === 'Backspace' ? 'backward' : 'forward') ||
                deleteEmptyCodeBlockAtCurrentSelection())
        ) {
            event.preventDefault()
            event.stopPropagation()
            return
        }

        if (
            mode === 'edit' &&
            event.target === event.currentTarget &&
            (event.key === 'ArrowDown' || event.key === 'ArrowUp') &&
            !event.shiftKey &&
            !event.altKey &&
            !event.metaKey &&
            !event.ctrlKey &&
            moveActiveRootInsertMenuSelection(event.currentTarget, event.key === 'ArrowDown' ? 'next' : 'previous')
        ) {
            event.preventDefault()
            event.stopPropagation()
            return
        }

        if (
            mode !== 'edit' ||
            event.target !== event.currentTarget ||
            event.key !== 'Enter' ||
            event.shiftKey ||
            event.altKey ||
            event.metaKey ||
            event.ctrlKey
        ) {
            return
        }

        if (submitActiveRootInsertMenu(event.currentTarget)) {
            event.preventDefault()
            event.stopPropagation()
            return
        }

        if (splitTextBlockAtCurrentSelection()) {
            event.preventDefault()
            event.stopPropagation()
        }
    }

    const lockFloatingToolbarPosition = (): void => {
        if (!floatingToolbar) {
            return
        }

        floatingToolbarPositionLockRef.current = {
            placement: floatingToolbar.placement,
            top: floatingToolbar.top,
            left: floatingToolbar.left,
        }
    }

    const renderedNodeGroups = getMarkdownNotebookVisualGroups(
        renderedNodes,
        insertMenu?.detached ? insertMenu.nodeId : undefined
    )

    const renderInsertBoundaryButton = (
        boundaryIndex: number,
        options: { isGapClickable?: boolean } = {}
    ): JSX.Element | null => {
        if (!showInsertBoundaries) {
            return null
        }

        return (
            <InsertBoundaryButton
                boundaryIndex={boundaryIndex}
                isAvailable={isInsertBoundaryAvailable(renderedNodes, boundaryIndex, insertMenu?.nodeId)}
                isVisible={isInsertBoundaryVisible(
                    renderedNodes,
                    boundaryIndex,
                    activeBoundaryIndex,
                    focusedRowIndex,
                    insertMenu?.nodeId
                )}
                isGapClickable={options.isGapClickable ?? true}
                focusPreviousNodeAtBoundaryEnd={focusPreviousNodeAtBoundaryEnd}
                openInsertMenuAtBoundary={openInsertMenuAtBoundary}
                setActiveBoundaryIndex={setActiveBoundaryIndex}
            />
        )
    }

    const renderNotebookRow = (node: NotebookBlockNode, index: number): JSX.Element => {
        const isTitleRow = index === 0
        const isInsertMenuOpen = insertMenu?.nodeId === node.id
        const insertMenuMode = isInsertMenuOpen ? (insertMenu.mode ?? 'tools') : null
        const isToolInsertMenuOpen = isInsertMenuOpen && insertMenuMode === 'tools'
        const isAIPromptOpen = isPromptComponentNode(node)
        const componentDefinition =
            node.type === 'component' ? getMarkdownNotebookComponentDefinition(mergedRegistry, node.tagName) : undefined
        const componentPanelCacheEntry = node.type === 'component' ? componentPanelCache[node.id] : undefined
        const persistComponentPanelVisibility =
            node.type === 'component' ? shouldPersistComponentPanelProps(node, componentDefinition) : false
        const nodeComponentPanels =
            node.type === 'component'
                ? !persistComponentPanelVisibility && componentPanelCacheEntry?.current
                    ? componentPanelCacheEntry.current
                    : getComponentPanelVisibility(node, DEFAULT_COMPONENT_PANEL_VISIBILITY)
                : DEFAULT_COMPONENT_PANEL_VISIBILITY
        const shouldShowInlineInsertMenuButton =
            !isTitleRow && (isBlankInsertMenuButtonRow(node) || (isToolInsertMenuOpen && isTextBlockNode(node)))
        const hasInvalidInsertMenuQuery =
            isToolInsertMenuOpen &&
            insertMenu.query.length > 0 &&
            getFilteredInsertCommands(insertCommands, insertMenu.query).length === 0

        return (
            <div
                className={clsx('MarkdownNotebook__row', isInsertMenuOpen && 'MarkdownNotebook__row--insert-menu-open')}
                onMouseEnter={(event) => updateActiveBoundaryFromRow(event, index)}
                onMouseMove={(event) => updateActiveBoundaryFromRow(event, index)}
                onFocusCapture={() => handleRowFocus(index)}
                onBlurCapture={(event) => handleRowBlur(event, index)}
            >
                {renderNode({
                    node,
                    nodeIndex: index,
                    mode,
                    placeholder: isTitleRow
                        ? NOTEBOOK_TITLE_PLACEHOLDER
                        : isToolInsertMenuOpen
                          ? INSERT_MENU_PLACEHOLDER
                          : isAIPromptOpen
                            ? ''
                            : node.id === placeholderNodeId
                              ? placeholder
                              : undefined,
                    registry: mergedRegistry,
                    componentPanels: nodeComponentPanels,
                    rememberedComponentPanels: componentPanelCacheEntry?.remembered,
                    persistComponentPanelVisibility,
                    isSelected: selectedComponentNodeIds.has(node.id),
                    toggleComponentPanel: (panel) =>
                        updateNode(node.id, (currentNode) => {
                            if (currentNode.type !== 'component') {
                                return currentNode
                            }

                            const currentPanels = getComponentPanelVisibility(
                                currentNode,
                                DEFAULT_COMPONENT_PANEL_VISIBILITY
                            )
                            const nextPanels = {
                                ...currentPanels,
                                [panel]: !currentPanels[panel],
                            }
                            return withPersistedComponentPanelProps(currentNode, componentDefinition, nextPanels)
                        }),
                    setLocalComponentPanels,
                    rememberComponentPanels,
                    setBlockRef: (element) => {
                        if (element) {
                            blockRefs.current[node.id] = element
                        } else if (!blockRefs.current[node.id]?.isConnected) {
                            delete blockRefs.current[node.id]
                        }
                    },
                    setListItemRef: (itemIndex, itemId, element) => {
                        listItemRefs.current[getListItemRefKey(node.id, itemIndex)] = element
                        if (itemId) {
                            listItemRefs.current[getListItemRefKey(node.id, itemId)] = element
                        }
                    },
                    setTableCellRef: (position, element) => {
                        tableCellRefs.current[getTableCellRefKey(node.id, position)] = element
                    },
                    updateNode,
                    replaceNodeWithNodes,
                    deleteNode: () => updateNode(node.id, () => null),
                    deleteNodeAndFocusAdjacent: () => {
                        requestFocusAfterRemovingNode(node.id)
                        updateNode(node.id, () => null)
                    },
                    deleteNodeAndFocusPrevious,
                    deleteSelectedNotebookBlocks,
                    insertParagraphAfterNode: () => insertEmptyParagraphAfterNode(node.id),
                    deleteNodeBefore,
                    moveFocusToAdjacentNode,
                    openInsertMenu: (query = '') => openInsertMenu(node.id, query),
                    openDetachedInsertMenu: () => openDetachedInsertMenuFromNode(node.id),
                    updateAIPromptQuery: (query) => updateAIPromptQuery(node.id, query),
                    closeInsertMenu: clearInsertMenu,
                    moveInsertMenuSelection: (direction) => {
                        setInsertMenu((currentMenu) => {
                            if (!currentMenu || currentMenu.nodeId !== node.id) {
                                return currentMenu
                            }

                            return {
                                ...currentMenu,
                                selectedIndex: getNextInsertMenuSelectedIndex(
                                    currentMenu.selectedIndex,
                                    getFilteredInsertCommands(insertCommands, currentMenu.query).length,
                                    direction
                                ),
                            }
                        })
                    },
                    toggleInsertMenu: () => {
                        if (isToolInsertMenuOpen || isAIPromptOpen) {
                            dismissInsertMenu()
                            return
                        }
                        openInsertMenu(node.id, getInlineInsertMenuQuery(node))
                    },
                    activateInlineInsertMenuButton: () => {
                        setActiveRowIndex(index)
                        setActiveBoundaryIndex(null)
                    },
                    showInlineInsertMenuButton: mode === 'edit' && shouldShowInlineInsertMenuButton,
                    isInlineInsertMenuButtonVisible: activeRowIndex === index || isToolInsertMenuOpen || isAIPromptOpen,
                    isInsertMenuOpen,
                    insertMenuMode,
                    hasInvalidInsertMenuQuery,
                    submitInsertMenuSelection: (queryOverride) =>
                        submitInsertMenuSelectionForNode(node.id, queryOverride),
                    submitAIPrompt: (queryOverride) => submitAIPromptForNode(node.id, queryOverride),
                    handleSelectionChange,
                    startTextSelectionPointer,
                    restoreSelectionRef,
                    rootEditableInputHtmlByNodeIdRef,
                })}
                {isToolInsertMenuOpen ? (
                    <InsertMenu
                        query={insertMenu.query}
                        commands={insertCommands}
                        targetNodeId={node.id}
                        position={insertMenuPosition}
                        selectedIndex={insertMenu.selectedIndex}
                        onClose={clearInsertMenu}
                    />
                ) : null}
            </div>
        )
    }

    return (
        <div
            className={clsx('MarkdownNotebook', isDebugOpen && 'MarkdownNotebook--debug-open', className)}
            data-attr={dataAttr}
            ref={notebookRef}
            onCopy={handleCopy}
            onCut={handleCut}
            onPaste={handleNotebookPaste}
            onKeyDownCapture={handleNotebookKeyDown}
        >
            <div className="MarkdownNotebook__debug-layout">
                <div className="MarkdownNotebook__main" onMouseDown={handleMainMouseDown}>
                    {showDebug ? (
                        <div className="MarkdownNotebook__debug-toolbar">
                            <LemonButton
                                size="xsmall"
                                icon={<IconCode />}
                                active={isDebugOpen}
                                aria-controls={debugDrawerId}
                                aria-expanded={isDebugOpen}
                                onClick={() => setIsDebugOpen((isOpen) => !isOpen)}
                            >
                                Debug
                            </LemonButton>
                        </div>
                    ) : null}
                    {document.errors.length ? (
                        <div className="MarkdownNotebook__parse-errors">
                            {document.errors.map((error) => (
                                <div key={`${error.line}:${error.message}`}>{error.message}</div>
                            ))}
                        </div>
                    ) : null}
                    <div
                        className="MarkdownNotebook__canvas"
                        ref={canvasRef}
                        contentEditable={mode === 'edit'}
                        suppressContentEditableWarning
                        data-markdown-notebook-editor
                        onInput={handleRootEditableInput}
                        onKeyDown={handleRootEditableKeyDown}
                        onMouseLeave={handleCanvasMouseLeave}
                    >
                        {renderInsertBoundaryButton(0)}
                        {renderedNodeGroups.map((group) => {
                            if (group.type === 'text') {
                                const lastItem = group.items[group.items.length - 1]

                                return (
                                    <Fragment key={group.key}>
                                        <div className="MarkdownNotebook__text-group">
                                            {group.items.map(({ node, index }) => (
                                                <Fragment key={node.id}>
                                                    {renderNotebookRow(node, index)}
                                                    {index < lastItem.index
                                                        ? renderInsertBoundaryButton(index + 1, {
                                                              isGapClickable: false,
                                                          })
                                                        : null}
                                                </Fragment>
                                            ))}
                                        </div>
                                        {renderInsertBoundaryButton(lastItem.index + 1)}
                                    </Fragment>
                                )
                            }

                            if (group.type === 'quote') {
                                const lastItem = group.items[group.items.length - 1]

                                return (
                                    <Fragment key={group.key}>
                                        <div className="MarkdownNotebook__blockquote-group">
                                            {group.items.map(({ node, index }) => (
                                                <Fragment key={node.id}>{renderNotebookRow(node, index)}</Fragment>
                                            ))}
                                        </div>
                                        {renderInsertBoundaryButton(lastItem.index + 1)}
                                    </Fragment>
                                )
                            }

                            return (
                                <Fragment key={group.key}>
                                    {renderNotebookRow(group.node, group.index)}
                                    {renderInsertBoundaryButton(group.index + 1)}
                                </Fragment>
                            )
                        })}
                    </div>
                    {floatingToolbar && mode === 'edit' ? (
                        <FormattingToolbar
                            selectedBlockStyle={getSelectedBlockStyle(
                                floatingToolbar.textRanges,
                                floatingToolbar.codeRanges,
                                floatingToolbar.listItemRanges
                            )}
                            placement={floatingToolbar.placement}
                            top={floatingToolbar.top}
                            left={floatingToolbar.left}
                            showInlineActions={
                                (floatingToolbar.textRanges.length > 0 || floatingToolbar.listItemRanges.length > 0) &&
                                floatingToolbar.codeRanges.length === 0
                            }
                            applyInlineMark={applyInlineMark}
                            applyInlineLink={applyInlineLink}
                            currentLinkHref={getFloatingToolbarLinkHref(floatingToolbar)}
                            initialLinkEditorOpen={floatingToolbar.isLinkEditorOpen ?? false}
                            setBlockStyle={setSelectedBlockStyle}
                            copySelection={copyFloatingToolbarSelection}
                            askAIAboutSelection={onAskAI ? askAIAboutSelection : undefined}
                            lockPosition={lockFloatingToolbarPosition}
                        />
                    ) : null}
                </div>
                {showDebug && isDebugOpen ? (
                    <aside className="MarkdownNotebook__debug-drawer" id={debugDrawerId}>
                        <div className="MarkdownNotebook__debug-drawer-header">
                            <span>Markdown</span>
                            <LemonButton size="xsmall" onClick={() => setIsDebugOpen(false)}>
                                Close
                            </LemonButton>
                        </div>
                        <textarea
                            ref={debugTextareaRef}
                            className="MarkdownNotebook__debug-markdown"
                            aria-label="Markdown debug output"
                            value={debugMarkdown}
                            onChange={handleDebugMarkdownChange}
                        />
                    </aside>
                ) : null}
            </div>
        </div>
    )
}
