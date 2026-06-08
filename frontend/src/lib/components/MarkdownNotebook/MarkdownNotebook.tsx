import './MarkdownNotebook.scss'

import clsx from 'clsx'
import {
    ChangeEvent as ReactChangeEvent,
    ClipboardEvent as ReactClipboardEvent,
    type CSSProperties,
    FocusEvent as ReactFocusEvent,
    FormEvent,
    Fragment,
    KeyboardEvent,
    MouseEvent as ReactMouseEvent,
    MutableRefObject,
    ReactNode,
    memo,
    useCallback,
    useEffect,
    useId,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from 'react'

import {
    IconCode,
    IconDatabase,
    IconEye,
    IconGraph,
    IconList,
    IconMinus,
    IconPencil,
    IconPlus,
    IconSparkles,
    IconTrash,
} from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { IconBold, IconItalic, IconLink } from 'lib/lemon-ui/icons'

import { mergeNotebookMarkdownChanges } from './collaboration'
import {
    htmlElementToInlineNodes,
    inlineNodesToHtml,
    makeEmptyParagraph,
    parseMarkdownNotebook,
    sanitizeNotebookLinkHref,
    serializeMarkdownNotebook,
} from './markdown'
import { reconcileNotebookDocuments } from './reconcile'
import {
    getMarkdownNotebookComponentDefinition,
    getMarkdownNotebookDefaultRegistry,
    mergeMarkdownNotebookRegistries,
} from './registry'
import {
    NotebookBlockNode,
    NotebookCollaborationConflict,
    NotebookComponentBlockNode,
    NotebookComponentDefinition,
    NotebookComponentProps,
    NotebookComponentRegistry,
    NotebookDocument,
    NotebookInlineMark,
    NotebookInlineNode,
    NotebookListBlockNode,
    NotebookListItem,
    NotebookMode,
    NotebookPropValue,
    NotebookTableBlockNode,
    NotebookTableCell,
    NotebookTextBlockNode,
    NotebookTextSelectionRange,
} from './types'
import {
    cloneNotebookDocument,
    cloneNotebookNode,
    getInlineText,
    getNodeFingerprint,
    normalizeInlineNodes,
} from './utils'

export type MarkdownNotebookProps = {
    value: string
    onChange?: (value: string) => void
    onAskAI?: (request: MarkdownNotebookAskAIRequest) => void
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
    query: string
    placeholderNodeId: string
    insertionPlaceholder: string
    markdown: string
    markdownWithPlaceholder: string
}

type RestoreSelectionRequest = {
    nodeId: string
    start: number
    end: number
    listItemIndex?: number
    tableCell?: TableCellPosition
}

type InsertCommand = {
    key: string
    label: string
    category: string
    description?: string
    aliases?: string[]
    icon?: JSX.Element
    closeOnRun?: boolean
    run: (targetNodeId: string) => void
}

type InsertMenuState = {
    nodeId: string
    query: string
    selectedIndex: number
    mode?: 'tools' | 'ai' | 'thinking'
}

type InsertMenuSelectionDirection = 'next' | 'previous'

type InsertMenuPosition = {
    placement: 'above' | 'below'
    top: number
    left: number
    width: number
    maxHeight: number
}

type FloatingToolbarState = {
    range: NotebookTextSelectionRange
    node: NotebookTextBlockNode
    placement: 'above' | 'below'
    top: number
    left: number
    isLinkEditorOpen?: boolean
}

type CrossBlockSelectionDragState = {
    anchorRange: Range
    anchorEditableElement: HTMLElement | null
    originX: number
    originY: number
    isDragging: boolean
}

type CommitDocumentOptions = {
    addToHistory?: boolean
}

type NotebookHistoryState = {
    undo: NotebookDocument[]
    redo: NotebookDocument[]
}

type InlineLinkPasteResult = {
    children: NotebookInlineNode[]
    start: number
    end: number
}

type ComponentPanel = 'view' | 'edit'

type ComponentPanelVisibility = Record<ComponentPanel, boolean>

type ComponentTitleTone = 'default' | 'insight' | 'sql' | 'data' | 'media' | 'experiment' | 'code' | 'posthog'

type ComponentTitleDisplay = {
    label: string
    tone: ComponentTitleTone
    icon: ReactNode
}

type RenderedListItem = NotebookListItem & {
    index: number
    childrenItems: RenderedListItem[]
}

type TableSection = 'header' | 'body'

type TableCellPosition = {
    section: TableSection
    rowIndex: number
    columnIndex: number
}

type NotebookComponentShellProps = {
    node: NotebookComponentBlockNode
    mode: NotebookMode
    componentPanels: ComponentPanelVisibility
    isSelected: boolean
    registry: NotebookComponentRegistry
    toggleComponentPanel: (panel: ComponentPanel) => void
    setBlockRef: (element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    deleteNode: () => void
    insertParagraphAfterNode: () => void
    moveFocusToAdjacentNode: (nodeId: string, direction: InsertMenuSelectionDirection, offset: number) => boolean
}

const DEFAULT_COMPONENT_PANEL_VISIBILITY: ComponentPanelVisibility = {
    view: true,
    edit: false,
}

const INSERTED_COMPONENT_PANEL_VISIBILITY: ComponentPanelVisibility = {
    view: true,
    edit: true,
}

const FLOATING_TOOLBAR_ESTIMATED_HEIGHT = 36
const CROSS_BLOCK_SELECTION_DRAG_THRESHOLD = 4
const INSERT_MENU_GAP = 12
const INSERT_MENU_MAX_HEIGHT = 448
const INSERT_MENU_MIN_HEIGHT = 120
const INSERT_MENU_PLACEHOLDER = 'Search for a tool'
const INSERT_MENU_WIDTH = 384
const INSERT_MENU_VIEWPORT_PADDING = 12
const MAX_UNDO_HISTORY_ENTRIES = 100
const NOTEBOOK_EDITABLE_BLOCK_SELECTOR =
    '.MarkdownNotebook__text-block, .MarkdownNotebook__list-item-content, .MarkdownNotebook__table-cell-content'
const NOTEBOOK_SELECTABLE_BLOCK_SELECTOR = `${NOTEBOOK_EDITABLE_BLOCK_SELECTOR}, .MarkdownNotebook__component-shell, .MarkdownNotebook__list-block, .MarkdownNotebook__table-block, .MarkdownNotebook__code-block`

function getAskAIMarkdownPlaceholder(placeholderNodeId: string): string {
    return `<!-- Ask PostHog AI insertion placeholder block id: ${placeholderNodeId} -->`
}

export function MarkdownNotebook({
    value,
    onChange,
    onAskAI,
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
        ensureEditableTrailingParagraph(parseMarkdownNotebook(value))
    )
    const [floatingToolbar, setFloatingToolbar] = useState<FloatingToolbarState | null>(null)
    const [insertMenu, setInsertMenu] = useState<InsertMenuState | null>(null)
    const [insertMenuPosition, setInsertMenuPosition] = useState<InsertMenuPosition | null>(null)
    const [activeRowIndex, setActiveRowIndex] = useState<number | null>(null)
    const [activeBoundaryIndex, setActiveBoundaryIndex] = useState<number | null>(null)
    const [focusedRowIndex, setFocusedRowIndex] = useState<number | null>(null)
    const [componentPanels, setComponentPanels] = useState<Record<string, ComponentPanelVisibility>>({})
    const [selectedComponentNodeIds, setSelectedComponentNodeIds] = useState<Set<string>>(() => new Set())
    const [isDebugOpen, setIsDebugOpen] = useState(false)
    const [debugMarkdown, setDebugMarkdown] = useState(value)
    const debugDrawerId = useId()
    const notebookRef = useRef<HTMLDivElement | null>(null)
    const canvasRef = useRef<HTMLDivElement | null>(null)
    const documentRef = useRef(document)
    const blockRefs = useRef<Record<string, HTMLElement | null>>({})
    const listItemRefs = useRef<Record<string, HTMLElement | null>>({})
    const tableCellRefs = useRef<Record<string, HTMLElement | null>>({})
    const aiThinkingTagRefs = useRef<Record<string, HTMLButtonElement | null>>({})
    const crossBlockSelectionRef = useRef<CrossBlockSelectionDragState | null>(null)
    const focusNodeRef = useRef<string | null>(null)
    const restoreSelectionRef = useRef<RestoreSelectionRequest | null>(null)
    const notebookClipboardMarkdownRef = useRef<string | null>(null)
    const historyRef = useRef<NotebookHistoryState>({ undo: [], redo: [] })
    const lastSerializedValueRef = useRef(value)
    const lastBaseValueRef = useRef(value)
    const lastRemoteValueRef = useRef(remoteValue)
    const pendingRemoteValueRef = useRef<string | null>(null)
    const initialInsertMenuAppliedRef = useRef(false)
    const emptyNodeRef = useRef<NotebookTextBlockNode>(makeEmptyParagraph('initial-empty'))
    const initializedComponentPanelNodeIdsRef = useRef<Set<string> | null>(null)

    useEffect(() => {
        if (!showDebug) {
            setIsDebugOpen(false)
        }
    }, [showDebug])

    useEffect(() => {
        if (value === lastSerializedValueRef.current) {
            return
        }

        setDocument((currentDocument) => {
            const nextDocument = parseMarkdownNotebook(value)
            const reconciledDocument = ensureEditableTrailingParagraph(
                reconcileNotebookDocuments(currentDocument, nextDocument).document
            )
            documentRef.current = reconciledDocument
            return reconciledDocument
        })
        setDebugMarkdown(value)
        historyRef.current = { undo: [], redo: [] }
        lastSerializedValueRef.current = value
        lastBaseValueRef.current = value
    }, [value])

    useLayoutEffect(() => {
        const request = restoreSelectionRef.current
        if (request) {
            restoreSelectionRef.current = null
            const element =
                request.tableCell !== undefined
                    ? tableCellRefs.current[getTableCellRefKey(request.nodeId, request.tableCell)]
                    : request.listItemIndex === undefined
                      ? blockRefs.current[request.nodeId]
                      : listItemRefs.current[getListItemRefKey(request.nodeId, request.listItemIndex)]
            if (element) {
                element.focus()
                restoreSelection(element, request.start, request.end)
            }
            return
        }

        const focusNodeId = focusNodeRef.current
        if (focusNodeId) {
            focusNodeRef.current = null
            blockRefs.current[focusNodeId]?.focus()
        }
    }, [document])

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
            const editableDocument = ensureEditableTrailingParagraph(nextDocument)
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
                lastRemoteValueRef.current = nextRemoteValue
                lastBaseValueRef.current = nextRemoteValue
                historyRef.current = { undo: [], redo: [] }
                return
            }

            const mergeResult = mergeNotebookMarkdownChanges({
                baseMarkdown: lastBaseValueRef.current,
                localMarkdown: lastSerializedValueRef.current,
                remoteMarkdown: nextRemoteValue,
            })
            const reconciledDocument = reconcileNotebookDocuments(documentRef.current, mergeResult.document).document
            lastRemoteValueRef.current = nextRemoteValue
            lastBaseValueRef.current = mergeResult.mergedMarkdown
            historyRef.current = { undo: [], redo: [] }
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
        if (insertMenu?.mode === 'thinking') {
            setInsertMenu(null)
        }
        applyRemoteValue(nextRemoteValue)
    }, [remoteValue, deferRemoteValue, applyRemoteValue, insertMenu?.mode])

    const isInsertMenuInteractionActive = !!insertMenu && insertMenu.mode !== 'thinking'
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
            const editableDocument = ensureEditableTrailingParagraph(cloneNotebookDocument(targetDocument))
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

    useEffect(() => {
        const notebookElement = notebookRef.current
        if (!notebookElement) {
            return
        }

        const handleBeforeInput = (event: Event): void => {
            if (mode !== 'edit') {
                return
            }

            const nativeEvent = event as InputEvent
            if (nativeEvent.inputType !== 'historyUndo' && nativeEvent.inputType !== 'historyRedo') {
                return
            }

            if (
                event.target instanceof HTMLElement &&
                (event.target.closest('.MarkdownNotebook__debug-drawer') || isNativeEditableElement(event.target))
            ) {
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
    }, [mode, redoHistory, undoHistory])

    const updateNode = useCallback(
        (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null): void => {
            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const nextNodes = nodes.flatMap((node) => {
                if (node.id !== nodeId) {
                    return [node]
                }
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
            setComponentPanels((currentPanels) => ({
                ...currentPanels,
                [nextNode.id]: INSERTED_COMPONENT_PANEL_VISIBILITY,
            }))
            focusNodeRef.current = nextNode.id
            replaceNode(nodeId, nextNode)
        },
        [replaceNode]
    )

    const replaceNodeWithNodes = useCallback(
        (nodeId: string, replacementNodes: NotebookBlockNode[]): void => {
            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            commitDocument({
                ...currentDocument,
                nodes: nodes.flatMap((node) => (node.id === nodeId ? replacementNodes : [node])),
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
        (nodeId: string): boolean => {
            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const nodeIndex = nodes.findIndex((node) => node.id === nodeId)
            if (nodeIndex <= 0) {
                return false
            }

            const previousNode = nodes[nodeIndex - 1]
            const currentNode = nodes[nodeIndex]
            if (isTextBlockNode(previousNode) && isTextBlockNode(currentNode)) {
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

            restoreSelectionRef.current = { nodeId, start: 0, end: 0 }
            commitDocument({
                ...currentDocument,
                nodes: nodes.filter((_, index) => index !== nodeIndex - 1),
            })
            return true
        },
        [commitDocument]
    )

    const openAIPrompt = useCallback(
        (nodeId: string): void => {
            onInteractionStateChange?.(true)
            updateNode(nodeId, (currentNode) => {
                if (!isTextBlockNode(currentNode)) {
                    return currentNode
                }
                return { ...currentNode, children: [] }
            })
            restoreSelectionRef.current = { nodeId, start: 0, end: 0 }
            setInsertMenu({ nodeId, query: '', selectedIndex: 0, mode: 'ai' })
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
                    restoreSelectionRef.current = {
                        nodeId,
                        tableCell: { section: 'header', rowIndex: 0, columnIndex: 0 },
                        start: 0,
                        end: 8,
                    }
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

        setComponentPanels((currentPanels) => {
            const nextPanels = { ...currentPanels }
            insertedComponentNodeIds.forEach((nodeId) => {
                nextPanels[nodeId] = INSERTED_COMPONENT_PANEL_VISIBILITY
            })
            return nextPanels
        })
    }, [document.nodes, mode])

    const updateFloatingToolbarFromSelection = useCallback((): void => {
        if (mode !== 'edit') {
            setFloatingToolbar(null)
            return
        }

        const selection = window.getSelection()
        if (!selection || selection.rangeCount === 0) {
            if (isFormattingToolbarFocused()) {
                return
            }
            setFloatingToolbar(null)
            return
        }

        const domRange = selection.getRangeAt(0)
        const selectedEntry = Object.entries(blockRefs.current).find(([, element]) =>
            element?.contains(domRange.commonAncestorContainer)
        )
        if (!selectedEntry) {
            if (isFormattingToolbarFocused()) {
                return
            }
            setFloatingToolbar(null)
            return
        }

        const [nodeId, element] = selectedEntry
        if (!element) {
            setFloatingToolbar(null)
            return
        }

        const selectedNode = documentRef.current.nodes.find(
            (node): node is NotebookTextBlockNode => node.id === nodeId && isTextBlockNode(node)
        )
        const range = getSelectionRange(element, nodeId)
        if (!selectedNode || !range) {
            setFloatingToolbar(null)
            return
        }

        if (range.start === range.end) {
            setFloatingToolbar(null)
            return
        }

        const selectionRect = getSelectionClientRect(domRange)
        if (!selectionRect) {
            setFloatingToolbar(null)
            return
        }

        const lineHeight = getElementLineHeight(element)
        const shouldPlaceBelow = selectionRect.top < FLOATING_TOOLBAR_ESTIMATED_HEIGHT + lineHeight

        setFloatingToolbar({
            range,
            node: selectedNode,
            placement: shouldPlaceBelow ? 'below' : 'above',
            top: Math.round(shouldPlaceBelow ? selectionRect.bottom + lineHeight : selectionRect.top),
            left: Math.min(
                window.innerWidth - 16,
                Math.max(16, Math.round(selectionRect.left + selectionRect.width / 2))
            ),
        })
    }, [mode])

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
            crossBlockSelectionRef.current = null
            return
        }

        const handleDocumentSelectionChange = (): void => {
            updateFloatingToolbarFromSelection()
            updateSelectedComponentBlocksFromSelection()
        }

        window.document.addEventListener('selectionchange', handleDocumentSelectionChange)
        window.addEventListener('resize', handleDocumentSelectionChange)
        window.addEventListener('scroll', handleDocumentSelectionChange, true)

        return () => {
            window.document.removeEventListener('selectionchange', handleDocumentSelectionChange)
            window.removeEventListener('resize', handleDocumentSelectionChange)
            window.removeEventListener('scroll', handleDocumentSelectionChange, true)
        }
    }, [mode, updateFloatingToolbarFromSelection])

    const handleSelectionChange = (): void => {
        updateFloatingToolbarFromSelection()
    }

    useEffect(() => {
        if (mode !== 'edit') {
            crossBlockSelectionRef.current = null
            return
        }

        const handleMouseMove = (event: MouseEvent): void => {
            const dragState = crossBlockSelectionRef.current
            const notebookElement = notebookRef.current
            if (!dragState || !notebookElement) {
                return
            }

            const distance = Math.hypot(event.clientX - dragState.originX, event.clientY - dragState.originY)
            if (distance < CROSS_BLOCK_SELECTION_DRAG_THRESHOLD) {
                return
            }

            const focusRange = getNotebookBlockCaretRangeFromPoint(event.clientX, event.clientY, notebookElement)
            if (!focusRange) {
                return
            }

            const focusEditableElement = getEditableBlockElementForRange(focusRange)
            if (dragState.anchorEditableElement && focusEditableElement === dragState.anchorEditableElement) {
                return
            }

            dragState.isDragging = true
            event.preventDefault()
            selectBetweenRanges(dragState.anchorRange, focusRange)
            setFloatingToolbar(null)
            updateSelectedComponentBlocksFromSelection()
        }

        const handleMouseUp = (): void => {
            const dragState = crossBlockSelectionRef.current
            crossBlockSelectionRef.current = null
            if (dragState?.isDragging) {
                updateFloatingToolbarFromSelection()
                updateSelectedComponentBlocksFromSelection()
            }
        }

        window.document.addEventListener('mousemove', handleMouseMove)
        window.document.addEventListener('mouseup', handleMouseUp)

        return () => {
            window.document.removeEventListener('mousemove', handleMouseMove)
            window.document.removeEventListener('mouseup', handleMouseUp)
        }
    }, [mode, updateFloatingToolbarFromSelection, updateSelectedComponentBlocksFromSelection])

    const startCrossBlockSelection = (event: ReactMouseEvent<HTMLElement>): void => {
        const notebookElement = notebookRef.current
        if (mode !== 'edit' || event.button !== 0 || !notebookElement) {
            return
        }

        const anchorRange = getNotebookBlockCaretRangeFromPoint(event.clientX, event.clientY, notebookElement)
        if (!anchorRange) {
            return
        }

        crossBlockSelectionRef.current = {
            anchorRange: anchorRange.cloneRange(),
            anchorEditableElement: getClosestEditableBlockElement(event.currentTarget),
            originX: event.clientX,
            originY: event.clientY,
            isDragging: false,
        }
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
        if (!markdown) {
            return
        }

        event.preventDefault()
        setClipboardMarkdown(event.clipboardData, markdown)
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
        const nextMarkdown = event.currentTarget.value
        const nextDocument = parseMarkdownNotebook(nextMarkdown)
        const reconciledDocument = ensureEditableTrailingParagraph(
            reconcileNotebookDocuments(documentRef.current, nextDocument).document
        )

        documentRef.current = reconciledDocument
        lastSerializedValueRef.current = nextMarkdown
        lastBaseValueRef.current = nextMarkdown
        setDebugMarkdown(nextMarkdown)
        setDocument(reconciledDocument)
        onChange?.(nextMarkdown)
    }

    const applyInlineMark = (markType: NotebookInlineMark['type']): void => {
        const activeSelectionRange = floatingToolbar?.range
        if (!activeSelectionRange) {
            return
        }

        restoreSelectionRef.current = activeSelectionRange
        updateNode(activeSelectionRange.nodeId, (node) => {
            if (!isTextBlockNode(node)) {
                return node
            }
            return {
                ...node,
                children: toggleInlineMark(node.children, activeSelectionRange, markType),
            }
        })
    }

    const applyInlineLink = (href: string | null): void => {
        const activeSelectionRange = floatingToolbar?.range
        if (!activeSelectionRange) {
            return
        }

        restoreSelectionRef.current = activeSelectionRange
        updateNode(activeSelectionRange.nodeId, (node) => {
            if (!isTextBlockNode(node)) {
                return node
            }
            return {
                ...node,
                children: setInlineLinkMark(node.children, activeSelectionRange, href),
            }
        })
        setFloatingToolbar(null)
    }

    const setBlockStyle = (nodeId: string, style: 'paragraph' | 'blockquote' | 1 | 2 | 3): void => {
        updateNode(nodeId, (node) => {
            if (!isTextBlockNode(node)) {
                return node
            }
            if (typeof style === 'number') {
                return { ...node, type: 'heading', level: style }
            }
            return { ...node, type: style, level: undefined }
        })
    }

    const openInsertMenu = (nodeId: string, query: string = ''): void => {
        onInteractionStateChange?.(true)
        setInsertMenu({ nodeId, query, selectedIndex: 0, mode: 'tools' })
    }

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
        if (!insertMenu || insertMenu.mode === 'thinking') {
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

            setInsertMenu(null)
        }

        window.document.addEventListener('pointerdown', closeInsertMenuOnOutsidePointerDown)

        return () => {
            window.document.removeEventListener('pointerdown', closeInsertMenuOnOutsidePointerDown)
        }
    }, [insertMenu])

    const insertEmptyParagraphAtBoundary = (boundaryIndex: number): void => {
        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes
        const insertedNode = makeEmptyParagraph(`boundary-${String(boundaryIndex)}`)
        const clampedBoundaryIndex = Math.max(0, Math.min(boundaryIndex, nodes.length))

        commitDocument({
            ...currentDocument,
            nodes: [...nodes.slice(0, clampedBoundaryIndex), insertedNode, ...nodes.slice(clampedBoundaryIndex)],
        })
        restoreSelectionRef.current = { nodeId: insertedNode.id, start: 0, end: 0 }
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
                const thinkingElement =
                    insertMenu?.mode === 'thinking' && insertMenu.nodeId === node.id
                        ? aiThinkingTagRefs.current[node.id]
                        : null
                if (thinkingElement) {
                    thinkingElement.focus()
                    return true
                }

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
            restoreSelectionRef.current = { nodeId: node.id, listItemIndex, start: offset, end: offset }
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

    const focusOrCreateTrailingBlankRow = useCallback((): boolean => {
        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
        const lastNode = nodes[nodes.length - 1]
        const isLastNodeAIThinking = insertMenu?.mode === 'thinking' && insertMenu.nodeId === lastNode?.id
        if (isTextBlockNode(lastNode) && !getInlineText(lastNode.children).trim() && !isLastNodeAIThinking) {
            const element = blockRefs.current[lastNode.id]
            if (element) {
                element.focus()
                restoreSelection(element, 0, 0)
                return true
            }
            restoreSelectionRef.current = { nodeId: lastNode.id, start: 0, end: 0 }
            return true
        }

        if (!currentDocument.nodes.length) {
            return focusLowestNotebookRow()
        }

        const insertedNode = makeEmptyParagraph(`after-${lastNode.id}`)
        restoreSelectionRef.current = { nodeId: insertedNode.id, start: 0, end: 0 }
        commitDocument({
            ...currentDocument,
            nodes: [...currentDocument.nodes, insertedNode],
        })
        return true
    }, [commitDocument, focusLowestNotebookRow, insertMenu])

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
                    const thinkingElement =
                        insertMenu?.mode === 'thinking' && insertMenu.nodeId === targetNode.id
                            ? aiThinkingTagRefs.current[targetNode.id]
                            : null
                    if (thinkingElement) {
                        thinkingElement.focus()
                        return true
                    }

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

    const moveFocusToAdjacentListItem = useCallback(
        (nodeId: string, itemIndex: number, direction: InsertMenuSelectionDirection, offset: number): boolean => {
            const nodes = documentRef.current.nodes.length ? documentRef.current.nodes : [emptyNodeRef.current]
            const node = nodes.find(
                (candidate): candidate is NotebookListBlockNode => candidate.id === nodeId && candidate.type === 'list'
            )
            if (!node) {
                return false
            }

            const nextItemIndex = itemIndex + (direction === 'next' ? 1 : -1)
            if (nextItemIndex >= 0 && nextItemIndex < node.items.length) {
                const element = listItemRefs.current[getListItemRefKey(nodeId, nextItemIndex)]
                if (!element) {
                    return false
                }

                const targetOffset = Math.min(offset, getInlineText(node.items[nextItemIndex].children).length)
                element.focus()
                restoreSelection(element, targetOffset, targetOffset)
                return true
            }

            return moveFocusToAdjacentNode(nodeId, direction, offset)
        },
        [moveFocusToAdjacentNode]
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
        const clickedCanvasBackground = event.target === canvasElement
        if (!clickedInsideCanvas && !clickedBelowCanvas) {
            return
        }

        if (
            clickedBelowCanvas || clickedCanvasBackground ? focusOrCreateTrailingBlankRow() : focusLowestNotebookRow()
        ) {
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

    return (
        <div
            className={clsx('MarkdownNotebook', isDebugOpen && 'MarkdownNotebook--debug-open', className)}
            data-attr={dataAttr}
            ref={notebookRef}
            onCopy={handleCopy}
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
                    <div className="MarkdownNotebook__canvas" ref={canvasRef} onMouseLeave={handleCanvasMouseLeave}>
                        {showInsertBoundaries ? (
                            <InsertBoundaryButton
                                boundaryIndex={0}
                                isAvailable={isInsertBoundaryAvailable(renderedNodes, 0, insertMenu?.nodeId)}
                                isVisible={isInsertBoundaryVisible(
                                    renderedNodes,
                                    0,
                                    activeBoundaryIndex,
                                    focusedRowIndex,
                                    insertMenu?.nodeId
                                )}
                                insertEmptyParagraphAtBoundary={insertEmptyParagraphAtBoundary}
                                setActiveBoundaryIndex={setActiveBoundaryIndex}
                            />
                        ) : null}
                        {renderedNodes.map((node, index) => {
                            const isInsertMenuOpen = insertMenu?.nodeId === node.id
                            const insertMenuMode = isInsertMenuOpen ? (insertMenu.mode ?? 'tools') : null
                            const isToolInsertMenuOpen = isInsertMenuOpen && insertMenuMode === 'tools'
                            const isAIPromptOpen = isInsertMenuOpen && insertMenuMode === 'ai'
                            const isAIThinking = isInsertMenuOpen && insertMenuMode === 'thinking'
                            const shouldShowInlineInsertMenuButton =
                                !isAIThinking &&
                                (isBlankInsertMenuButtonRow(node) ||
                                    ((isToolInsertMenuOpen || isAIPromptOpen) && isTextBlockNode(node)))
                            const hasInvalidInsertMenuQuery =
                                isToolInsertMenuOpen &&
                                insertMenu.query.length > 0 &&
                                getFilteredInsertCommands(insertCommands, insertMenu.query).length === 0
                            const submitInsertMenuSelection = (queryOverride?: string): boolean => {
                                if (!isToolInsertMenuOpen) {
                                    return false
                                }

                                const query = queryOverride ?? insertMenu.query
                                const filteredCommands = getFilteredInsertCommands(insertCommands, query)
                                const selectedIndex =
                                    query === insertMenu.query
                                        ? getClampedInsertMenuSelectedIndex(
                                              insertMenu.selectedIndex,
                                              filteredCommands.length
                                          )
                                        : 0
                                const selectedCommand = filteredCommands[selectedIndex]
                                if (!selectedCommand) {
                                    if (query.length > 0) {
                                        updateNode(node.id, (currentNode) => {
                                            if (!isTextBlockNode(currentNode)) {
                                                return currentNode
                                            }
                                            return { ...currentNode, children: [] }
                                        })
                                        restoreSelectionRef.current = { nodeId: node.id, start: 0, end: 0 }
                                        setInsertMenu({ nodeId: node.id, query: '', selectedIndex: 0 })
                                        return true
                                    }
                                    return false
                                }

                                selectedCommand.run(node.id)
                                if (selectedCommand.closeOnRun === false) {
                                    return true
                                }
                                if (selectedCommand.key.startsWith('text-')) {
                                    updateNode(node.id, (currentNode) => {
                                        if (!isTextBlockNode(currentNode)) {
                                            return currentNode
                                        }
                                        return { ...currentNode, children: [] }
                                    })
                                    restoreSelectionRef.current = { nodeId: node.id, start: 0, end: 0 }
                                }
                                setInsertMenu(null)
                                return true
                            }
                            const submitAIPrompt = (queryOverride?: string): boolean => {
                                if (!isAIPromptOpen || !onAskAI) {
                                    return false
                                }

                                const query = (queryOverride ?? insertMenu.query).trim()
                                if (!query) {
                                    return false
                                }

                                const currentDocument = documentRef.current
                                const nodes = currentDocument.nodes.length
                                    ? currentDocument.nodes
                                    : [emptyNodeRef.current]
                                const nextDocument = {
                                    ...currentDocument,
                                    nodes: nodes.map((currentNode) => {
                                        if (currentNode.id !== node.id || !isTextBlockNode(currentNode)) {
                                            return currentNode
                                        }
                                        return { ...currentNode, children: [] }
                                    }),
                                }
                                commitDocument(nextDocument)
                                restoreSelectionRef.current = { nodeId: node.id, start: 0, end: 0 }
                                setInsertMenu({ nodeId: node.id, query: '', selectedIndex: 0, mode: 'thinking' })
                                const insertionPlaceholder = getAskAIMarkdownPlaceholder(node.id)
                                const markdownWithPlaceholder = serializeMarkdownNotebook({
                                    ...nextDocument,
                                    nodes: nextDocument.nodes.map((currentNode) =>
                                        currentNode.id === node.id
                                            ? {
                                                  id: currentNode.id,
                                                  type: 'paragraph',
                                                  children: [
                                                      {
                                                          type: 'text',
                                                          text: insertionPlaceholder,
                                                      },
                                                  ],
                                              }
                                            : currentNode
                                    ),
                                })
                                onAskAI({
                                    query,
                                    placeholderNodeId: node.id,
                                    insertionPlaceholder,
                                    markdown: serializeMarkdownNotebook(nextDocument),
                                    markdownWithPlaceholder,
                                })
                                return true
                            }

                            return (
                                <Fragment key={node.id}>
                                    <div
                                        className={clsx(
                                            'MarkdownNotebook__row',
                                            isInsertMenuOpen && 'MarkdownNotebook__row--insert-menu-open'
                                        )}
                                        onMouseEnter={(event) => updateActiveBoundaryFromRow(event, index)}
                                        onMouseMove={(event) => updateActiveBoundaryFromRow(event, index)}
                                        onFocusCapture={() => handleRowFocus(index)}
                                        onBlurCapture={(event) => handleRowBlur(event, index)}
                                    >
                                        {renderNode({
                                            node,
                                            mode,
                                            placeholder: isToolInsertMenuOpen
                                                ? INSERT_MENU_PLACEHOLDER
                                                : isAIPromptOpen
                                                  ? ''
                                                  : node.id === placeholderNodeId
                                                    ? placeholder
                                                    : undefined,
                                            registry: mergedRegistry,
                                            componentPanels:
                                                componentPanels[node.id] ?? DEFAULT_COMPONENT_PANEL_VISIBILITY,
                                            isSelected: selectedComponentNodeIds.has(node.id),
                                            toggleComponentPanel: (panel) =>
                                                setComponentPanels((current) => {
                                                    const currentPanels =
                                                        current[node.id] ?? DEFAULT_COMPONENT_PANEL_VISIBILITY
                                                    return {
                                                        ...current,
                                                        [node.id]: {
                                                            ...currentPanels,
                                                            [panel]: !currentPanels[panel],
                                                        },
                                                    }
                                                }),
                                            setBlockRef: (element) => {
                                                blockRefs.current[node.id] = element
                                            },
                                            setAIThinkingTagRef: (element) => {
                                                aiThinkingTagRefs.current[node.id] = element
                                            },
                                            setListItemRef: (itemIndex, element) => {
                                                listItemRefs.current[getListItemRefKey(node.id, itemIndex)] = element
                                            },
                                            setTableCellRef: (position, element) => {
                                                tableCellRefs.current[getTableCellRefKey(node.id, position)] = element
                                            },
                                            getTableCellElement: (position) =>
                                                tableCellRefs.current[getTableCellRefKey(node.id, position)] ?? null,
                                            updateNode,
                                            replaceNodeWithNodes,
                                            deleteNode: () => updateNode(node.id, () => null),
                                            deleteNodeAndFocusAdjacent: () => {
                                                requestFocusAfterRemovingNode(node.id)
                                                updateNode(node.id, () => null)
                                            },
                                            insertParagraphAfterNode: () => insertEmptyParagraphAfterNode(node.id),
                                            deleteNodeBefore,
                                            moveFocusToAdjacentNode,
                                            moveFocusToAdjacentListItem,
                                            moveFocusToAdjacentTableCell,
                                            openInsertMenu: (query = '') => openInsertMenu(node.id, query),
                                            updateAIPromptQuery: (query) => updateAIPromptQuery(node.id, query),
                                            closeInsertMenu: () => setInsertMenu(null),
                                            moveInsertMenuSelection: (direction) => {
                                                setInsertMenu((currentMenu) => {
                                                    if (!currentMenu || currentMenu.nodeId !== node.id) {
                                                        return currentMenu
                                                    }

                                                    return {
                                                        ...currentMenu,
                                                        selectedIndex: getNextInsertMenuSelectedIndex(
                                                            currentMenu.selectedIndex,
                                                            getFilteredInsertCommands(insertCommands, currentMenu.query)
                                                                .length,
                                                            direction
                                                        ),
                                                    }
                                                })
                                            },
                                            toggleInsertMenu: () => {
                                                if (isToolInsertMenuOpen || isAIPromptOpen) {
                                                    setInsertMenu(null)
                                                    return
                                                }
                                                openInsertMenu(node.id, getInlineInsertMenuQuery(node))
                                            },
                                            showInlineInsertMenuButton:
                                                mode === 'edit' && shouldShowInlineInsertMenuButton,
                                            isInlineInsertMenuButtonVisible:
                                                activeRowIndex === index || isToolInsertMenuOpen || isAIPromptOpen,
                                            isInsertMenuOpen,
                                            insertMenuMode,
                                            hasInvalidInsertMenuQuery,
                                            submitInsertMenuSelection,
                                            submitAIPrompt,
                                            handleSelectionChange,
                                            startCrossBlockSelection,
                                            restoreSelectionRef,
                                        })}
                                        {isToolInsertMenuOpen ? (
                                            <InsertMenu
                                                query={insertMenu.query}
                                                commands={insertCommands}
                                                targetNodeId={node.id}
                                                position={insertMenuPosition}
                                                selectedIndex={insertMenu.selectedIndex}
                                                onClose={() => setInsertMenu(null)}
                                            />
                                        ) : null}
                                    </div>
                                    {showInsertBoundaries ? (
                                        <InsertBoundaryButton
                                            boundaryIndex={index + 1}
                                            isAvailable={isInsertBoundaryAvailable(
                                                renderedNodes,
                                                index + 1,
                                                insertMenu?.nodeId
                                            )}
                                            isVisible={isInsertBoundaryVisible(
                                                renderedNodes,
                                                index + 1,
                                                activeBoundaryIndex,
                                                focusedRowIndex,
                                                insertMenu?.nodeId
                                            )}
                                            insertEmptyParagraphAtBoundary={insertEmptyParagraphAtBoundary}
                                            setActiveBoundaryIndex={setActiveBoundaryIndex}
                                        />
                                    ) : null}
                                </Fragment>
                            )
                        })}
                    </div>
                    {floatingToolbar && mode === 'edit' ? (
                        <FormattingToolbar
                            node={floatingToolbar.node}
                            placement={floatingToolbar.placement}
                            top={floatingToolbar.top}
                            left={floatingToolbar.left}
                            applyInlineMark={applyInlineMark}
                            applyInlineLink={applyInlineLink}
                            currentLinkHref={getSelectedLinkHref(floatingToolbar.node.children, floatingToolbar.range)}
                            initialLinkEditorOpen={floatingToolbar.isLinkEditorOpen ?? false}
                            setBlockStyle={setBlockStyle}
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

function renderNode({
    node,
    mode,
    placeholder,
    registry,
    componentPanels,
    isSelected,
    toggleComponentPanel,
    setBlockRef,
    setAIThinkingTagRef,
    setListItemRef,
    setTableCellRef,
    getTableCellElement,
    updateNode,
    replaceNodeWithNodes,
    deleteNode,
    deleteNodeAndFocusAdjacent,
    insertParagraphAfterNode,
    deleteNodeBefore,
    moveFocusToAdjacentNode,
    moveFocusToAdjacentListItem,
    moveFocusToAdjacentTableCell,
    openInsertMenu,
    updateAIPromptQuery,
    closeInsertMenu,
    moveInsertMenuSelection,
    toggleInsertMenu,
    showInlineInsertMenuButton,
    isInlineInsertMenuButtonVisible,
    isInsertMenuOpen,
    insertMenuMode,
    hasInvalidInsertMenuQuery,
    submitInsertMenuSelection,
    submitAIPrompt,
    handleSelectionChange,
    startCrossBlockSelection,
    restoreSelectionRef,
}: {
    node: NotebookBlockNode
    mode: NotebookMode
    placeholder: string | undefined
    registry: NotebookComponentRegistry
    componentPanels: ComponentPanelVisibility
    isSelected: boolean
    toggleComponentPanel: (panel: ComponentPanel) => void
    setBlockRef: (element: HTMLElement | null) => void
    setAIThinkingTagRef: (element: HTMLButtonElement | null) => void
    setListItemRef: (itemIndex: number, element: HTMLElement | null) => void
    setTableCellRef: (position: TableCellPosition, element: HTMLElement | null) => void
    getTableCellElement: (position: TableCellPosition) => HTMLElement | null
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    replaceNodeWithNodes: (nodeId: string, replacementNodes: NotebookBlockNode[]) => void
    deleteNode: () => void
    deleteNodeAndFocusAdjacent: () => void
    insertParagraphAfterNode: () => void
    deleteNodeBefore: (nodeId: string) => boolean
    moveFocusToAdjacentNode: (nodeId: string, direction: InsertMenuSelectionDirection, offset: number) => boolean
    moveFocusToAdjacentListItem: (
        nodeId: string,
        itemIndex: number,
        direction: InsertMenuSelectionDirection,
        offset: number
    ) => boolean
    moveFocusToAdjacentTableCell: (
        nodeId: string,
        position: TableCellPosition,
        direction: InsertMenuSelectionDirection,
        offset: number
    ) => boolean
    openInsertMenu: (query?: string) => void
    updateAIPromptQuery: (query: string) => void
    closeInsertMenu: () => void
    moveInsertMenuSelection: (direction: InsertMenuSelectionDirection) => void
    toggleInsertMenu: () => void
    showInlineInsertMenuButton: boolean
    isInlineInsertMenuButtonVisible: boolean
    isInsertMenuOpen: boolean
    insertMenuMode: InsertMenuState['mode'] | null
    hasInvalidInsertMenuQuery: boolean
    submitInsertMenuSelection: (queryOverride?: string) => boolean
    submitAIPrompt: (queryOverride?: string) => boolean
    handleSelectionChange: () => void
    startCrossBlockSelection: (event: ReactMouseEvent<HTMLElement>) => void
    restoreSelectionRef: MutableRefObject<RestoreSelectionRequest | null>
}): JSX.Element {
    if (node.type === 'component') {
        return (
            <MemoizedNotebookComponentShell
                node={node}
                mode={mode}
                componentPanels={componentPanels}
                isSelected={isSelected}
                registry={registry}
                toggleComponentPanel={toggleComponentPanel}
                setBlockRef={setBlockRef}
                updateNode={updateNode}
                deleteNode={deleteNode}
                insertParagraphAfterNode={insertParagraphAfterNode}
                moveFocusToAdjacentNode={moveFocusToAdjacentNode}
            />
        )
    }

    if (node.type === 'list') {
        return (
            <EditableListBlock
                node={node}
                mode={mode}
                setBlockRef={setBlockRef}
                setListItemRef={setListItemRef}
                updateNode={updateNode}
                replaceNodeWithNodes={replaceNodeWithNodes}
                deleteNodeBefore={deleteNodeBefore}
                moveFocusToAdjacentListItem={moveFocusToAdjacentListItem}
                handleSelectionChange={handleSelectionChange}
                startCrossBlockSelection={startCrossBlockSelection}
                restoreSelectionRef={restoreSelectionRef}
            />
        )
    }

    if (node.type === 'table') {
        return (
            <EditableTableBlock
                node={node}
                mode={mode}
                setBlockRef={setBlockRef}
                setTableCellRef={setTableCellRef}
                getTableCellElement={getTableCellElement}
                updateNode={updateNode}
                moveFocusToAdjacentTableCell={moveFocusToAdjacentTableCell}
                handleSelectionChange={handleSelectionChange}
                startCrossBlockSelection={startCrossBlockSelection}
                restoreSelectionRef={restoreSelectionRef}
            />
        )
    }

    if (node.type === 'code') {
        return (
            <pre className="MarkdownNotebook__code-block" ref={setBlockRef}>
                <code>{node.text}</code>
            </pre>
        )
    }

    return (
        <EditableTextBlock
            node={node}
            mode={mode}
            placeholder={placeholder}
            setBlockRef={setBlockRef}
            setAIThinkingTagRef={setAIThinkingTagRef}
            updateNode={updateNode}
            replaceNodeWithNodes={replaceNodeWithNodes}
            deleteNodeAndFocusAdjacent={deleteNodeAndFocusAdjacent}
            deleteNodeBefore={deleteNodeBefore}
            moveFocusToAdjacentNode={moveFocusToAdjacentNode}
            openInsertMenu={openInsertMenu}
            updateAIPromptQuery={updateAIPromptQuery}
            closeInsertMenu={closeInsertMenu}
            moveInsertMenuSelection={moveInsertMenuSelection}
            toggleInsertMenu={toggleInsertMenu}
            showInlineInsertMenuButton={showInlineInsertMenuButton}
            isInlineInsertMenuButtonVisible={isInlineInsertMenuButtonVisible}
            isInsertMenuOpen={isInsertMenuOpen}
            insertMenuMode={insertMenuMode}
            hasInvalidInsertMenuQuery={hasInvalidInsertMenuQuery}
            submitInsertMenuSelection={submitInsertMenuSelection}
            submitAIPrompt={submitAIPrompt}
            handleSelectionChange={handleSelectionChange}
            startCrossBlockSelection={startCrossBlockSelection}
            restoreSelectionRef={restoreSelectionRef}
        />
    )
}

function EditableListBlock({
    node,
    mode,
    setBlockRef,
    setListItemRef,
    updateNode,
    replaceNodeWithNodes,
    deleteNodeBefore,
    moveFocusToAdjacentListItem,
    handleSelectionChange,
    startCrossBlockSelection,
    restoreSelectionRef,
}: {
    node: NotebookListBlockNode
    mode: NotebookMode
    setBlockRef: (element: HTMLElement | null) => void
    setListItemRef: (itemIndex: number, element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    replaceNodeWithNodes: (nodeId: string, replacementNodes: NotebookBlockNode[]) => void
    deleteNodeBefore: (nodeId: string) => boolean
    moveFocusToAdjacentListItem: (
        nodeId: string,
        itemIndex: number,
        direction: InsertMenuSelectionDirection,
        offset: number
    ) => boolean
    handleSelectionChange: () => void
    startCrossBlockSelection: (event: ReactMouseEvent<HTMLElement>) => void
    restoreSelectionRef: MutableRefObject<RestoreSelectionRequest | null>
}): JSX.Element {
    const renderedItems = useMemo(() => buildRenderedListItems(node.items), [node.items])

    const updateListItem = (itemIndex: number, updater: (item: NotebookListItem) => NotebookListItem): void => {
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'list') {
                return currentNode
            }

            return {
                ...currentNode,
                items: currentNode.items.map((item, index) => (index === itemIndex ? updater(item) : item)),
            }
        })
    }

    const updateListItemChildren = (itemIndex: number, children: NotebookInlineNode[]): void => {
        updateListItem(itemIndex, (item) => ({ ...item, children }))
    }

    const shiftListItemDepth = (itemIndex: number, direction: 'in' | 'out', offset: number = 0): boolean => {
        const item = node.items[itemIndex]
        if (!item) {
            return false
        }

        const maximumDepth = itemIndex === 0 ? 0 : node.items[itemIndex - 1].depth + 1
        const nextDepth = direction === 'in' ? Math.min(item.depth + 1, maximumDepth) : Math.max(0, item.depth - 1)
        const depthDelta = nextDepth - item.depth
        if (depthDelta === 0) {
            return false
        }

        const subtreeEndIndex = getListItemSubtreeEndIndex(node.items, itemIndex)
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'list') {
                return currentNode
            }

            return {
                ...currentNode,
                items: currentNode.items.map((currentItem, index) =>
                    index >= itemIndex && index < subtreeEndIndex
                        ? { ...currentItem, depth: Math.max(0, currentItem.depth + depthDelta) }
                        : currentItem
                ),
            }
        })
        restoreSelectionRef.current = { nodeId: node.id, listItemIndex: itemIndex, start: offset, end: offset }
        return true
    }

    const removeListItem = (itemIndex: number): void => {
        const nextItems = node.items.filter((_, index) => index !== itemIndex)
        if (!nextItems.length) {
            const paragraph = makeEmptyParagraph(`after-list-${node.id}`)
            replaceNodeWithNodes(node.id, [paragraph])
            restoreSelectionRef.current = { nodeId: paragraph.id, start: 0, end: 0 }
            return
        }

        replaceNodeWithNodes(node.id, [{ ...node, items: nextItems }])
        const nextItemIndex = Math.max(0, Math.min(itemIndex, nextItems.length - 1))
        restoreSelectionRef.current = {
            nodeId: node.id,
            listItemIndex: nextItemIndex,
            start: 0,
            end: 0,
        }
    }

    const splitListItem = (itemIndex: number, offset: number): void => {
        const item = node.items[itemIndex]
        if (!item) {
            return
        }

        if (!getInlineText(item.children).length) {
            const paragraph = makeEmptyParagraph(`after-list-${node.id}`)
            const nextItems = node.items.filter((_, index) => index !== itemIndex)
            replaceNodeWithNodes(node.id, nextItems.length ? [{ ...node, items: nextItems }, paragraph] : [paragraph])
            restoreSelectionRef.current = { nodeId: paragraph.id, start: 0, end: 0 }
            return
        }

        const [before, after] = splitInlineNodesAt(item.children, offset)
        const nextItem: NotebookListItem = {
            children: after,
            depth: item.depth,
            ordered: item.ordered ?? node.ordered,
        }
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'list') {
                return currentNode
            }

            const nextItems = [...currentNode.items]
            nextItems[itemIndex] = { ...nextItems[itemIndex], children: before }
            nextItems.splice(itemIndex + 1, 0, nextItem)
            return { ...currentNode, items: nextItems }
        })
        restoreSelectionRef.current = {
            nodeId: node.id,
            listItemIndex: itemIndex + 1,
            start: 0,
            end: 0,
        }
    }

    const renderItems = (items: RenderedListItem[], ordered: boolean): ReactNode => {
        const ListTag = ordered ? 'ol' : 'ul'
        return (
            <ListTag>
                {items.map((item) => {
                    const itemOrdered = item.ordered ?? ordered
                    return (
                        <li key={item.index}>
                            <EditableListItemContent
                                node={node}
                                item={item}
                                mode={mode}
                                setListItemRef={setListItemRef}
                                updateListItemChildren={updateListItemChildren}
                                splitListItem={splitListItem}
                                removeListItem={removeListItem}
                                shiftListItemDepth={shiftListItemDepth}
                                deleteNodeBefore={deleteNodeBefore}
                                moveFocusToAdjacentListItem={moveFocusToAdjacentListItem}
                                handleSelectionChange={handleSelectionChange}
                                startCrossBlockSelection={startCrossBlockSelection}
                                restoreSelectionRef={restoreSelectionRef}
                            />
                            {item.childrenItems.length
                                ? renderItems(item.childrenItems, item.childrenItems[0].ordered ?? itemOrdered)
                                : null}
                        </li>
                    )
                })}
            </ListTag>
        )
    }

    return (
        <div className="MarkdownNotebook__list-block" ref={setBlockRef}>
            {renderItems(renderedItems, node.ordered)}
        </div>
    )
}

function EditableListItemContent({
    node,
    item,
    mode,
    setListItemRef,
    updateListItemChildren,
    splitListItem,
    removeListItem,
    shiftListItemDepth,
    deleteNodeBefore,
    moveFocusToAdjacentListItem,
    handleSelectionChange,
    startCrossBlockSelection,
    restoreSelectionRef,
}: {
    node: NotebookListBlockNode
    item: RenderedListItem
    mode: NotebookMode
    setListItemRef: (itemIndex: number, element: HTMLElement | null) => void
    updateListItemChildren: (itemIndex: number, children: NotebookInlineNode[]) => void
    splitListItem: (itemIndex: number, offset: number) => void
    removeListItem: (itemIndex: number) => void
    shiftListItemDepth: (itemIndex: number, direction: 'in' | 'out', offset?: number) => boolean
    deleteNodeBefore: (nodeId: string) => boolean
    moveFocusToAdjacentListItem: (
        nodeId: string,
        itemIndex: number,
        direction: InsertMenuSelectionDirection,
        offset: number
    ) => boolean
    handleSelectionChange: () => void
    startCrossBlockSelection: (event: ReactMouseEvent<HTMLElement>) => void
    restoreSelectionRef: MutableRefObject<RestoreSelectionRequest | null>
}): JSX.Element {
    const elementRef = useRef<HTMLDivElement | null>(null)
    const skipDomSyncForHtmlRef = useRef<string | null>(null)
    const renderedHtml = useMemo(() => inlineNodesToHtml(item.children), [item.children])

    const setElementRef = useCallback(
        (element: HTMLDivElement | null): void => {
            elementRef.current = element
            setListItemRef(item.index, element)
        },
        [item.index, setListItemRef]
    )

    useLayoutEffect(() => {
        const element = elementRef.current
        if (!element) {
            return
        }

        const shouldSkipOwnInputSync =
            document.activeElement === element && skipDomSyncForHtmlRef.current === renderedHtml
        skipDomSyncForHtmlRef.current = null

        if (shouldSkipOwnInputSync || element.innerHTML === renderedHtml) {
            return
        }

        element.innerHTML = renderedHtml
    }, [renderedHtml])

    const updateChildren = (nextChildren: NotebookInlineNode[]): NotebookInlineNode[] => {
        skipDomSyncForHtmlRef.current = inlineNodesToHtml(nextChildren)
        updateListItemChildren(item.index, nextChildren)
        return nextChildren
    }

    const handleInput = (event: FormEvent<HTMLDivElement>): void => {
        updateChildren(htmlElementToInlineNodes(event.currentTarget))
    }

    const handlePaste = (event: ReactClipboardEvent<HTMLDivElement>): void => {
        const plainText = event.clipboardData.getData('text/plain')
        const html = event.clipboardData.getData('text/html')
        const linkPasteResult = getInlineLinkPasteResult(event.currentTarget, node.id, item.children, plainText)
        if (linkPasteResult) {
            event.preventDefault()
            updateChildren(linkPasteResult.children)
            restoreSelectionRef.current = {
                nodeId: node.id,
                listItemIndex: item.index,
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
            const selection = getSelectionRange(event.currentTarget, node.id)
            const currentTextLength = getInlineText(item.children).length
            const selectionStart = selection ? Math.min(selection.start, selection.end) : currentTextLength
            const selectionEnd = selection ? Math.max(selection.start, selection.end) : currentTextLength
            const [beforeSelection, selectionAndAfter] = splitInlineNodesAt(item.children, selectionStart)
            const [, afterSelection] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)
            const nextChildren = normalizeInlineNodes([
                ...beforeSelection,
                ...pastedDocument.nodes[0].children,
                ...afterSelection,
            ])
            const nextCaretOffset =
                getInlineText(beforeSelection).length + getInlineText(pastedDocument.nodes[0].children).length
            updateChildren(nextChildren)
            restoreSelectionRef.current = {
                nodeId: node.id,
                listItemIndex: item.index,
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
        updateChildren(htmlElementToInlineNodes(event.currentTarget))
    }

    const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
        if (event.key === 'Tab') {
            const selection = getCollapsedSelectionRange(event.currentTarget, node.id)
            if (shiftListItemDepth(item.index, event.shiftKey ? 'out' : 'in', selection?.start ?? 0)) {
                event.preventDefault()
            }
            return
        }

        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            const selection = getCollapsedSelectionRange(event.currentTarget, node.id)
            if (
                selection &&
                moveFocusToAdjacentListItem(
                    node.id,
                    item.index,
                    event.key === 'ArrowDown' ? 'next' : 'previous',
                    selection.start
                )
            ) {
                event.preventDefault()
            }
            return
        }

        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            const selection = getCollapsedSelectionRange(event.currentTarget, node.id)
            splitListItem(item.index, selection?.start ?? getInlineText(item.children).length)
            return
        }

        if (event.key === 'Backspace') {
            const selection = getCollapsedSelectionRange(event.currentTarget, node.id)
            if (!selection || selection.start !== 0 || selection.end !== 0) {
                return
            }

            if (!getInlineText(item.children).length) {
                event.preventDefault()
                removeListItem(item.index)
                return
            }

            if (item.depth > 0 && shiftListItemDepth(item.index, 'out', 0)) {
                event.preventDefault()
                return
            }

            if (item.index === 0 && deleteNodeBefore(node.id)) {
                event.preventDefault()
            }
        }
    }

    return (
        <div
            ref={setElementRef}
            className="MarkdownNotebook__list-item-content"
            contentEditable={mode === 'edit'}
            suppressContentEditableWarning
            onInput={handleInput}
            onPaste={handlePaste}
            onKeyDown={handleKeyDown}
            onMouseDown={startCrossBlockSelection}
            onMouseUp={handleSelectionChange}
            onKeyUp={handleSelectionChange}
        />
    )
}

type TableStructureControlLayout = {
    tableLeft: number
    tableTop: number
    tableWidth: number
    tableHeight: number
    rowInsertTops: number[]
    rowRemoveRects: { top: number; height: number }[]
    columnInsertLefts: number[]
    columnRemoveRects: { left: number; width: number }[]
}

function areNumberArraysEqual(left: number[], right: number[]): boolean {
    return left.length === right.length && left.every((value, index) => value === right[index])
}

function areControlRectsEqual(
    left: { top?: number; left?: number; width?: number; height?: number }[],
    right: { top?: number; left?: number; width?: number; height?: number }[]
): boolean {
    return (
        left.length === right.length &&
        left.every((value, index) => {
            const rightValue = right[index]
            return (
                value.top === rightValue.top &&
                value.left === rightValue.left &&
                value.width === rightValue.width &&
                value.height === rightValue.height
            )
        })
    )
}

function areTableStructureControlLayoutsEqual(
    left: TableStructureControlLayout | null,
    right: TableStructureControlLayout
): boolean {
    return Boolean(
        left &&
        left.tableLeft === right.tableLeft &&
        left.tableTop === right.tableTop &&
        left.tableWidth === right.tableWidth &&
        left.tableHeight === right.tableHeight &&
        areNumberArraysEqual(left.rowInsertTops, right.rowInsertTops) &&
        areControlRectsEqual(left.rowRemoveRects, right.rowRemoveRects) &&
        areNumberArraysEqual(left.columnInsertLefts, right.columnInsertLefts) &&
        areControlRectsEqual(left.columnRemoveRects, right.columnRemoveRects)
    )
}

function tableControlStyle(variables: Record<string, string>): CSSProperties {
    return variables as CSSProperties
}

function EditableTableBlock({
    node,
    mode,
    setBlockRef,
    setTableCellRef,
    getTableCellElement,
    updateNode,
    moveFocusToAdjacentTableCell,
    handleSelectionChange,
    startCrossBlockSelection,
    restoreSelectionRef,
}: {
    node: NotebookTableBlockNode
    mode: NotebookMode
    setBlockRef: (element: HTMLElement | null) => void
    setTableCellRef: (position: TableCellPosition, element: HTMLElement | null) => void
    getTableCellElement: (position: TableCellPosition) => HTMLElement | null
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    moveFocusToAdjacentTableCell: (
        nodeId: string,
        position: TableCellPosition,
        direction: InsertMenuSelectionDirection,
        offset: number
    ) => boolean
    handleSelectionChange: () => void
    startCrossBlockSelection: (event: ReactMouseEvent<HTMLElement>) => void
    restoreSelectionRef: MutableRefObject<RestoreSelectionRequest | null>
}): JSX.Element {
    const columnCount = getTableColumnCount(node)
    const headers = normalizeTableRow(node.headers, columnCount)
    const rows = node.rows.map((row) => normalizeTableRow(row, columnCount))
    const tableGridRef = useRef<HTMLDivElement | null>(null)
    const tableRef = useRef<HTMLTableElement | null>(null)
    const [controlLayout, setControlLayout] = useState<TableStructureControlLayout | null>(null)

    const updateTableControlLayout = useCallback((): void => {
        if (mode !== 'edit') {
            return
        }

        const tableGrid = tableGridRef.current
        const table = tableRef.current
        if (!tableGrid || !table) {
            return
        }

        const gridRect = tableGrid.getBoundingClientRect()
        const tableRect = table.getBoundingClientRect()
        const headerRow = table.tHead?.rows[0]
        const bodyRows = Array.from(table.tBodies[0]?.rows ?? [])
        const headerCells = headerRow ? Array.from(headerRow.cells) : []

        const rowInsertTops = headerRow
            ? [
                  headerRow.getBoundingClientRect().bottom - gridRect.top,
                  ...bodyRows.map((row) => row.getBoundingClientRect().bottom - gridRect.top),
              ]
            : []
        const rowRemoveRects = bodyRows.map((row) => {
            const rowRect = row.getBoundingClientRect()
            return {
                top: rowRect.top - gridRect.top,
                height: rowRect.height,
            }
        })
        const columnInsertLefts = headerCells.length
            ? [
                  headerCells[0].getBoundingClientRect().left - gridRect.left,
                  ...headerCells.map((cell) => cell.getBoundingClientRect().right - gridRect.left),
              ]
            : []
        const columnRemoveRects = headerCells.map((cell) => {
            const cellRect = cell.getBoundingClientRect()
            return {
                left: cellRect.left - gridRect.left,
                width: cellRect.width,
            }
        })

        const nextLayout: TableStructureControlLayout = {
            tableLeft: tableRect.left - gridRect.left,
            tableTop: tableRect.top - gridRect.top,
            tableWidth: tableRect.width,
            tableHeight: tableRect.height,
            rowInsertTops,
            rowRemoveRects,
            columnInsertLefts,
            columnRemoveRects,
        }

        setControlLayout((previousLayout) =>
            areTableStructureControlLayoutsEqual(previousLayout, nextLayout) ? previousLayout : nextLayout
        )
    }, [mode])

    useLayoutEffect(() => {
        updateTableControlLayout()
    }, [columnCount, rows.length, updateTableControlLayout])

    useEffect(() => {
        if (mode !== 'edit') {
            return
        }

        const table = tableRef.current
        const ownerWindow = table?.ownerDocument.defaultView
        if (!table || !ownerWindow) {
            return
        }

        updateTableControlLayout()

        if (ownerWindow.ResizeObserver) {
            const resizeObserver = new ownerWindow.ResizeObserver(updateTableControlLayout)
            resizeObserver.observe(table)
            return () => resizeObserver.disconnect()
        }

        ownerWindow.addEventListener('resize', updateTableControlLayout)
        return () => ownerWindow.removeEventListener('resize', updateTableControlLayout)
    }, [mode, updateTableControlLayout])

    const updateTableCell = (position: TableCellPosition, children: NotebookInlineNode[]): void => {
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'table') {
                return currentNode
            }

            if (position.section === 'header') {
                const nextHeaders = normalizeTableRow(currentNode.headers, columnCount)
                nextHeaders[position.columnIndex] = { children }
                return { ...currentNode, headers: nextHeaders }
            }

            const nextRows = currentNode.rows.map((row) => normalizeTableRow(row, columnCount))
            const nextRow = nextRows[position.rowIndex] ?? makeEmptyTableRow(columnCount)
            nextRow[position.columnIndex] = { children }
            nextRows[position.rowIndex] = nextRow
            return { ...currentNode, rows: nextRows }
        })
    }

    const addTableRowAfter = (rowIndex: number, columnIndex: number): void => {
        const insertIndex = Math.max(0, Math.min(rowIndex + 1, rows.length))
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'table') {
                return currentNode
            }

            const nextRows = currentNode.rows.map((row) => normalizeTableRow(row, columnCount))
            nextRows.splice(insertIndex, 0, makeEmptyTableRow(columnCount))
            return { ...currentNode, rows: nextRows }
        })
        restoreSelectionRef.current = {
            nodeId: node.id,
            tableCell: { section: 'body', rowIndex: insertIndex, columnIndex },
            start: 0,
            end: 0,
        }
    }

    const removeTableRow = (rowIndex: number): void => {
        if (!rows.length) {
            return
        }

        const removeIndex = Math.max(0, Math.min(rowIndex, rows.length - 1))
        const nextRowCount = rows.length - 1
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'table') {
                return currentNode
            }

            const nextRows = currentNode.rows
                .map((row) => normalizeTableRow(row, columnCount))
                .filter((_, currentRowIndex) => currentRowIndex !== removeIndex)
            return { ...currentNode, rows: nextRows }
        })
        restoreSelectionRef.current = nextRowCount
            ? {
                  nodeId: node.id,
                  tableCell: {
                      section: 'body',
                      rowIndex: Math.max(0, Math.min(removeIndex, nextRowCount - 1)),
                      columnIndex: 0,
                  },
                  start: 0,
                  end: 0,
              }
            : {
                  nodeId: node.id,
                  tableCell: { section: 'header', rowIndex: 0, columnIndex: 0 },
                  start: 0,
                  end: 0,
              }
    }

    const addTableColumnAfter = (columnIndex: number): void => {
        const insertIndex = Math.max(0, Math.min(columnIndex + 1, columnCount))
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'table') {
                return currentNode
            }

            const nextHeaders = normalizeTableRow(currentNode.headers, columnCount)
            nextHeaders.splice(insertIndex, 0, { children: [] })
            const nextRows = currentNode.rows.map((row) => {
                const nextRow = normalizeTableRow(row, columnCount)
                nextRow.splice(insertIndex, 0, { children: [] })
                return nextRow
            })
            const nextAlignments = currentNode.alignments
                ? Array.from({ length: columnCount }, (_, index) => currentNode.alignments?.[index])
                : undefined
            nextAlignments?.splice(insertIndex, 0, undefined)

            return {
                ...currentNode,
                headers: nextHeaders,
                rows: nextRows,
                alignments: nextAlignments,
            }
        })
        restoreSelectionRef.current = {
            nodeId: node.id,
            tableCell: { section: 'header', rowIndex: 0, columnIndex: insertIndex },
            start: 0,
            end: 0,
        }
    }

    const removeTableColumn = (columnIndex: number): void => {
        if (columnCount <= 1) {
            return
        }

        const removeIndex = Math.max(0, Math.min(columnIndex, columnCount - 1))
        const nextColumnIndex = Math.max(0, Math.min(removeIndex, columnCount - 2))
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'table') {
                return currentNode
            }

            const nextHeaders = normalizeTableRow(currentNode.headers, columnCount).filter(
                (_, currentColumnIndex) => currentColumnIndex !== removeIndex
            )
            const nextRows = currentNode.rows.map((row) =>
                normalizeTableRow(row, columnCount).filter(
                    (_, currentColumnIndex) => currentColumnIndex !== removeIndex
                )
            )
            const nextAlignments = currentNode.alignments
                ? Array.from({ length: columnCount }, (_, index) => currentNode.alignments?.[index]).filter(
                      (_, currentColumnIndex) => currentColumnIndex !== removeIndex
                  )
                : undefined

            return {
                ...currentNode,
                headers: nextHeaders,
                rows: nextRows,
                alignments: nextAlignments,
            }
        })
        restoreSelectionRef.current = {
            nodeId: node.id,
            tableCell: { section: 'header', rowIndex: 0, columnIndex: nextColumnIndex },
            start: 0,
            end: 0,
        }
    }

    const focusTableCell = (position: TableCellPosition, offset: number = 0): void => {
        const element = getTableCellElement(position)
        if (element) {
            element.focus()
            restoreSelection(element, offset, offset)
            return
        }
        restoreSelectionRef.current = { nodeId: node.id, tableCell: position, start: offset, end: offset }
    }

    const handleTableCellEnter = (position: TableCellPosition): void => {
        if (position.section === 'header') {
            if (!node.rows.length) {
                addTableRowAfter(-1, position.columnIndex)
                return
            }
            focusTableCell({ section: 'body', rowIndex: 0, columnIndex: position.columnIndex })
            return
        }

        addTableRowAfter(position.rowIndex, position.columnIndex)
    }

    const tableLeft = controlLayout?.tableLeft ?? 0
    const tableTop = controlLayout?.tableTop ?? 0
    const tableWidth = controlLayout?.tableWidth ?? 0
    const tableHeight = controlLayout?.tableHeight ?? 0
    const rowInsertControls = [
        {
            key: 'row-start',
            rowIndex: -1,
            top: controlLayout?.rowInsertTops[0] ?? tableTop,
            label: rows.length ? 'Add row before row 1' : 'Add row',
            tooltip: rows.length ? 'Add row above' : 'Add row',
        },
        ...rows.map((_, rowIndex) => ({
            key: `row-after-${rowIndex}`,
            rowIndex,
            top: controlLayout?.rowInsertTops[rowIndex + 1] ?? tableTop,
            label: `Add row after row ${rowIndex + 1}`,
            tooltip: 'Add row below',
        })),
    ]
    const columnInsertControls = [
        {
            key: 'column-start',
            columnIndex: -1,
            left: controlLayout?.columnInsertLefts[0] ?? tableLeft,
            label: 'Add column before column 1',
            tooltip: 'Add column before',
        },
        ...headers.map((_, columnIndex) => ({
            key: `column-after-${columnIndex}`,
            columnIndex,
            left: controlLayout?.columnInsertLefts[columnIndex + 1] ?? tableLeft,
            label: `Add column after column ${columnIndex + 1}`,
            tooltip: 'Add column after',
        })),
    ]

    return (
        <div
            className={clsx(
                'MarkdownNotebook__table-block',
                mode === 'edit' && 'MarkdownNotebook__table-block--editable'
            )}
            ref={setBlockRef}
        >
            <div className="MarkdownNotebook__table-scroll">
                <div className="MarkdownNotebook__table-grid" ref={tableGridRef}>
                    <table ref={tableRef}>
                        <thead>
                            <tr>
                                {headers.map((cell, columnIndex) => (
                                    <th key={columnIndex}>
                                        <EditableTableCellContent
                                            node={node}
                                            cell={cell}
                                            position={{ section: 'header', rowIndex: 0, columnIndex }}
                                            mode={mode}
                                            setTableCellRef={setTableCellRef}
                                            updateTableCell={updateTableCell}
                                            moveFocusToAdjacentTableCell={moveFocusToAdjacentTableCell}
                                            handleTableCellEnter={handleTableCellEnter}
                                            handleSelectionChange={handleSelectionChange}
                                            startCrossBlockSelection={startCrossBlockSelection}
                                            restoreSelectionRef={restoreSelectionRef}
                                        />
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((row, rowIndex) => (
                                <tr key={rowIndex}>
                                    {row.map((cell, columnIndex) => (
                                        <td key={columnIndex}>
                                            <EditableTableCellContent
                                                node={node}
                                                cell={cell}
                                                position={{ section: 'body', rowIndex, columnIndex }}
                                                mode={mode}
                                                setTableCellRef={setTableCellRef}
                                                updateTableCell={updateTableCell}
                                                moveFocusToAdjacentTableCell={moveFocusToAdjacentTableCell}
                                                handleTableCellEnter={handleTableCellEnter}
                                                handleSelectionChange={handleSelectionChange}
                                                startCrossBlockSelection={startCrossBlockSelection}
                                                restoreSelectionRef={restoreSelectionRef}
                                            />
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {mode === 'edit' ? (
                        <div className="MarkdownNotebook__table-structure-overlay">
                            {rowInsertControls.map((control) => (
                                <div
                                    className="MarkdownNotebook__table-add-zone MarkdownNotebook__table-row-add-zone"
                                    key={control.key}
                                    style={tableControlStyle({
                                        '--table-control-left': `${tableLeft}px`,
                                        '--table-control-top': `${control.top}px`,
                                        '--table-control-width': `${tableWidth}px`,
                                    })}
                                >
                                    <TableStructureControlButton
                                        label={control.label}
                                        tooltip={control.tooltip}
                                        icon={<IconPlus />}
                                        onClick={() => addTableRowAfter(control.rowIndex, 0)}
                                    />
                                </div>
                            ))}
                            {columnInsertControls.map((control) => (
                                <div
                                    className="MarkdownNotebook__table-add-zone MarkdownNotebook__table-column-add-zone"
                                    key={control.key}
                                    style={tableControlStyle({
                                        '--table-control-left': `${control.left}px`,
                                        '--table-control-top': `${tableTop}px`,
                                        '--table-control-height': `${tableHeight}px`,
                                    })}
                                >
                                    <TableStructureControlButton
                                        label={control.label}
                                        tooltip={control.tooltip}
                                        icon={<IconPlus />}
                                        onClick={() => addTableColumnAfter(control.columnIndex)}
                                    />
                                </div>
                            ))}
                            {rows.map((_, rowIndex) => {
                                const rowRect = controlLayout?.rowRemoveRects[rowIndex]
                                return (
                                    <div
                                        className="MarkdownNotebook__table-remove-zone MarkdownNotebook__table-row-remove-zone"
                                        key={`remove-row-${rowIndex}`}
                                        style={tableControlStyle({
                                            '--table-control-left': `${tableLeft}px`,
                                            '--table-control-top': `${rowRect?.top ?? tableTop}px`,
                                            '--table-control-height': `${rowRect?.height ?? 0}px`,
                                        })}
                                    >
                                        <TableStructureControlButton
                                            label={`Remove row ${rowIndex + 1}`}
                                            tooltip="Remove row"
                                            icon={<IconMinus />}
                                            onClick={() => removeTableRow(rowIndex)}
                                        />
                                    </div>
                                )
                            })}
                            {headers.map((_, columnIndex) => {
                                const columnRect = controlLayout?.columnRemoveRects[columnIndex]
                                return (
                                    <div
                                        className="MarkdownNotebook__table-remove-zone MarkdownNotebook__table-column-remove-zone"
                                        key={`remove-column-${columnIndex}`}
                                        style={tableControlStyle({
                                            '--table-control-left': `${columnRect?.left ?? tableLeft}px`,
                                            '--table-control-top': `${tableTop}px`,
                                            '--table-control-width': `${columnRect?.width ?? 0}px`,
                                        })}
                                    >
                                        <TableStructureControlButton
                                            label={`Remove column ${columnIndex + 1}`}
                                            tooltip="Remove column"
                                            icon={<IconMinus />}
                                            disabledReason={
                                                columnCount <= 1 ? 'Tables need at least one column' : undefined
                                            }
                                            onClick={() => removeTableColumn(columnIndex)}
                                        />
                                    </div>
                                )
                            })}
                        </div>
                    ) : null}
                </div>
            </div>
        </div>
    )
}

function TableStructureControlButton({
    label,
    tooltip,
    icon,
    disabledReason,
    onClick,
}: {
    label: string
    tooltip: string
    icon: JSX.Element
    disabledReason?: string
    onClick: () => void
}): JSX.Element {
    return (
        <LemonButton
            aria-label={label}
            className="MarkdownNotebook__table-structure-control"
            disabledReason={disabledReason}
            icon={icon}
            noPadding
            size="xsmall"
            tooltip={tooltip}
            onClick={onClick}
            onMouseDown={(event) => {
                event.preventDefault()
                event.stopPropagation()
            }}
        />
    )
}

function EditableTableCellContent({
    node,
    cell,
    position,
    mode,
    setTableCellRef,
    updateTableCell,
    moveFocusToAdjacentTableCell,
    handleTableCellEnter,
    handleSelectionChange,
    startCrossBlockSelection,
    restoreSelectionRef,
}: {
    node: NotebookTableBlockNode
    cell: NotebookTableCell
    position: TableCellPosition
    mode: NotebookMode
    setTableCellRef: (position: TableCellPosition, element: HTMLElement | null) => void
    updateTableCell: (position: TableCellPosition, children: NotebookInlineNode[]) => void
    moveFocusToAdjacentTableCell: (
        nodeId: string,
        position: TableCellPosition,
        direction: InsertMenuSelectionDirection,
        offset: number
    ) => boolean
    handleTableCellEnter: (position: TableCellPosition) => void
    handleSelectionChange: () => void
    startCrossBlockSelection: (event: ReactMouseEvent<HTMLElement>) => void
    restoreSelectionRef: MutableRefObject<RestoreSelectionRequest | null>
}): JSX.Element {
    const elementRef = useRef<HTMLDivElement | null>(null)
    const skipDomSyncForHtmlRef = useRef<string | null>(null)
    const renderedHtml = useMemo(() => inlineNodesToHtml(cell.children), [cell.children])

    const setElementRef = useCallback(
        (element: HTMLDivElement | null): void => {
            elementRef.current = element
            setTableCellRef(position, element)
        },
        [position, setTableCellRef]
    )

    useLayoutEffect(() => {
        const element = elementRef.current
        if (!element) {
            return
        }

        const shouldSkipOwnInputSync =
            document.activeElement === element && skipDomSyncForHtmlRef.current === renderedHtml
        skipDomSyncForHtmlRef.current = null

        if (shouldSkipOwnInputSync || element.innerHTML === renderedHtml) {
            return
        }

        element.innerHTML = renderedHtml
    }, [renderedHtml])

    const updateChildren = (nextChildren: NotebookInlineNode[]): NotebookInlineNode[] => {
        skipDomSyncForHtmlRef.current = inlineNodesToHtml(nextChildren)
        updateTableCell(position, nextChildren)
        return nextChildren
    }

    const handleInput = (event: FormEvent<HTMLDivElement>): void => {
        updateChildren(htmlElementToInlineNodes(event.currentTarget))
    }

    const handlePaste = (event: ReactClipboardEvent<HTMLDivElement>): void => {
        const plainText = event.clipboardData.getData('text/plain')
        const html = event.clipboardData.getData('text/html')
        const linkPasteResult = getInlineLinkPasteResult(event.currentTarget, node.id, cell.children, plainText)
        if (linkPasteResult) {
            event.preventDefault()
            updateChildren(linkPasteResult.children)
            restoreSelectionRef.current = {
                nodeId: node.id,
                tableCell: position,
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
            const selection = getSelectionRange(event.currentTarget, node.id)
            const currentTextLength = getInlineText(cell.children).length
            const selectionStart = selection ? Math.min(selection.start, selection.end) : currentTextLength
            const selectionEnd = selection ? Math.max(selection.start, selection.end) : currentTextLength
            const [beforeSelection, selectionAndAfter] = splitInlineNodesAt(cell.children, selectionStart)
            const [, afterSelection] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)
            const nextChildren = normalizeInlineNodes([
                ...beforeSelection,
                ...pastedDocument.nodes[0].children,
                ...afterSelection,
            ])
            const nextCaretOffset =
                getInlineText(beforeSelection).length + getInlineText(pastedDocument.nodes[0].children).length
            updateChildren(nextChildren)
            restoreSelectionRef.current = {
                nodeId: node.id,
                tableCell: position,
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
        updateChildren(htmlElementToInlineNodes(event.currentTarget))
    }

    const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
        if (event.key === 'Tab') {
            event.preventDefault()
            const selection = getCollapsedSelectionRange(event.currentTarget, node.id)
            moveFocusToAdjacentTableCell(node.id, position, event.shiftKey ? 'previous' : 'next', selection?.start ?? 0)
            return
        }

        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            handleTableCellEnter(position)
            return
        }
    }

    return (
        <div
            ref={setElementRef}
            className="MarkdownNotebook__table-cell-content"
            contentEditable={mode === 'edit'}
            suppressContentEditableWarning
            onInput={handleInput}
            onPaste={handlePaste}
            onKeyDown={handleKeyDown}
            onMouseDown={startCrossBlockSelection}
            onMouseUp={handleSelectionChange}
            onKeyUp={handleSelectionChange}
        />
    )
}

function EditableTextBlock({
    node,
    mode,
    placeholder,
    setBlockRef,
    setAIThinkingTagRef,
    updateNode,
    replaceNodeWithNodes,
    deleteNodeAndFocusAdjacent,
    deleteNodeBefore,
    moveFocusToAdjacentNode,
    openInsertMenu,
    updateAIPromptQuery,
    closeInsertMenu,
    moveInsertMenuSelection,
    toggleInsertMenu,
    showInlineInsertMenuButton,
    isInlineInsertMenuButtonVisible,
    isInsertMenuOpen,
    insertMenuMode,
    hasInvalidInsertMenuQuery,
    submitInsertMenuSelection,
    submitAIPrompt,
    handleSelectionChange,
    startCrossBlockSelection,
    restoreSelectionRef,
}: {
    node: NotebookTextBlockNode
    mode: NotebookMode
    placeholder: string | undefined
    setBlockRef: (element: HTMLElement | null) => void
    setAIThinkingTagRef: (element: HTMLButtonElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    replaceNodeWithNodes: (nodeId: string, replacementNodes: NotebookBlockNode[]) => void
    deleteNodeAndFocusAdjacent: () => void
    deleteNodeBefore: (nodeId: string) => boolean
    moveFocusToAdjacentNode: (nodeId: string, direction: InsertMenuSelectionDirection, offset: number) => boolean
    openInsertMenu: (query?: string) => void
    updateAIPromptQuery: (query: string) => void
    closeInsertMenu: () => void
    moveInsertMenuSelection: (direction: InsertMenuSelectionDirection) => void
    toggleInsertMenu: () => void
    showInlineInsertMenuButton: boolean
    isInlineInsertMenuButtonVisible: boolean
    isInsertMenuOpen: boolean
    insertMenuMode: InsertMenuState['mode'] | null
    hasInvalidInsertMenuQuery: boolean
    submitInsertMenuSelection: (queryOverride?: string) => boolean
    submitAIPrompt: (queryOverride?: string) => boolean
    handleSelectionChange: () => void
    startCrossBlockSelection: (event: ReactMouseEvent<HTMLElement>) => void
    restoreSelectionRef: MutableRefObject<RestoreSelectionRequest | null>
}): JSX.Element {
    const elementRef = useRef<HTMLElement | null>(null)
    const skipDomSyncForHtmlRef = useRef<string | null>(null)
    const renderedHtml = useMemo(() => inlineNodesToHtml(node.children), [node.children])
    const text = getInlineText(node.children)
    const isEmpty = text.length === 0
    const isToolInsertMenuOpen = isInsertMenuOpen && (!insertMenuMode || insertMenuMode === 'tools')
    const isAIPromptOpen = isInsertMenuOpen && insertMenuMode === 'ai'
    const isAIThinking = isInsertMenuOpen && insertMenuMode === 'thinking'
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

        const shouldSkipOwnInputSync =
            document.activeElement === element && skipDomSyncForHtmlRef.current === renderedHtml
        skipDomSyncForHtmlRef.current = null

        if (shouldSkipOwnInputSync || element.innerHTML === renderedHtml) {
            return
        }

        element.innerHTML = renderedHtml
    }, [renderedHtml, TextTag])

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
                children: currentNode.children,
            }
        })
        restoreSelectionRef.current = { nodeId: node.id, start, end }
    }

    const removeAIThinkingPlaceholder = (): void => {
        closeInsertMenu()
        deleteNodeAndFocusAdjacent()
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
        const element = event.currentTarget
        const elementChildren = htmlElementToInlineNodes(element)
        const elementText = getInlineText(elementChildren)

        if (isAIThinking) {
            return
        }

        if (isAIPromptOpen) {
            const nextChildren = updateChildren(elementChildren)
            updateAIPromptQuery(getInlineText(nextChildren))
            return
        }

        const headingShortcut = getHeadingShortcut(elementText, node.type === 'heading' ? (node.level ?? 1) : null)
        if (headingShortcut !== null) {
            closeInsertMenu()
            event.currentTarget.innerHTML = ''
            replaceNodeWithNodes(node.id, [
                {
                    id: node.id,
                    type: 'heading',
                    level: headingShortcut,
                    children: [],
                },
            ])
            restoreSelectionRef.current = { nodeId: node.id, start: 0, end: 0 }
            return
        }

        if (node.type === 'paragraph' && getBlockquoteShortcut(elementText)) {
            closeInsertMenu()
            replaceNodeWithNodes(node.id, [
                {
                    id: node.id,
                    type: 'blockquote',
                    children: [],
                },
            ])
            restoreSelectionRef.current = { nodeId: node.id, start: 0, end: 0 }
            return
        }

        const listShortcut = getListShortcut(elementText)
        if (node.type === 'paragraph' && listShortcut) {
            closeInsertMenu()
            replaceNodeWithNodes(node.id, [
                {
                    id: node.id,
                    type: 'list',
                    ordered: listShortcut.ordered,
                    items: [
                        {
                            children: [],
                            depth: 0,
                            ordered: listShortcut.ordered,
                        },
                    ],
                },
            ])
            restoreSelectionRef.current = { nodeId: node.id, listItemIndex: 0, start: 0, end: 0 }
            return
        }

        const slashQuery = getSlashCommandQuery(elementText)
        if (slashQuery !== null) {
            if (isToolInsertMenuOpen) {
                updateElementAndChildren(element, [])
                closeInsertMenu()
                return
            }

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
        if (isToolInsertMenuOpen && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'a') {
            event.preventDefault()
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
            if (isAIPromptOpen) {
                if (submitAIPrompt(inputText)) {
                    event.preventDefault()
                }
                return
            }

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

            const nextParagraph = makeEmptyParagraph(`after-${node.id}`)
            nextParagraph.children = after

            replaceNodeWithNodes(node.id, [{ ...node, children: before }, nextParagraph])
            restoreSelectionRef.current = { nodeId: nextParagraph.id, start: 0, end: 0 }
            return
        }

        if (event.key === 'Backspace' || event.key === 'Delete') {
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
            if (event.key === 'Backspace' && isAIPromptOpen && selection?.start === 0 && selection.end === 0) {
                event.preventDefault()
                replaceWithParagraph(0)
                return
            }

            if (event.key === 'Backspace' && node.type === 'heading' && selection?.start === 0 && selection.end === 0) {
                event.preventDefault()
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

            if (isEmpty) {
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
        toggleInsertMenu()
        focusEditableBlock()
    }

    const handleAIThinkingTagKeyDown = (event: KeyboardEvent<HTMLButtonElement>): void => {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            if (moveFocusToAdjacentNode(node.id, event.key === 'ArrowDown' ? 'next' : 'previous', 0)) {
                event.preventDefault()
            }
            return
        }

        if (event.key === 'Backspace' || event.key === 'Delete') {
            event.preventDefault()
            removeAIThinkingPlaceholder()
        }
    }

    return (
        <div
            className={clsx(
                'MarkdownNotebook__text-row',
                (isAIPromptOpen || isAIThinking) && 'MarkdownNotebook__text-row--ai-prompt',
                isAIThinking && 'MarkdownNotebook__text-row--ai-thinking',
                showInlineInsertMenuButton &&
                    isInlineInsertMenuButtonVisible &&
                    'MarkdownNotebook__text-row--inline-menu-visible'
            )}
        >
            {showInlineInsertMenuButton ? (
                <LemonButton
                    size="xsmall"
                    icon={<span className="MarkdownNotebook__line-insert-menu-icon">/</span>}
                    className="MarkdownNotebook__line-insert-menu-button"
                    active={isToolInsertMenuOpen}
                    tooltip="Add block"
                    onClick={handleInsertMenuButtonClick}
                    aria-label={isInsertMenuOpen ? 'Close add block menu' : 'Open add block menu'}
                    aria-expanded={isInsertMenuOpen}
                    tabIndex={isInlineInsertMenuButtonVisible ? 0 : -1}
                />
            ) : null}
            {isAIPromptOpen || isAIThinking ? (
                <button
                    type="button"
                    ref={isAIThinking ? setAIThinkingTagRef : undefined}
                    className={clsx(
                        'MarkdownNotebook__ai-prompt-tag',
                        isAIThinking && 'MarkdownNotebook__ai-prompt-tag--thinking'
                    )}
                    aria-label={isAIThinking ? 'AI response placeholder' : 'Ask AI prompt'}
                    tabIndex={isAIThinking ? 0 : -1}
                    onClick={(event) => {
                        if (isAIThinking) {
                            event.currentTarget.focus()
                        }
                    }}
                    onKeyDown={isAIThinking ? handleAIThinkingTagKeyDown : undefined}
                >
                    <IconSparkles />
                    {isAIThinking ? 'Thinking ...' : 'Ask AI'}
                </button>
            ) : null}
            <TextTag
                ref={setElementRef}
                className={clsx(
                    'MarkdownNotebook__text-block',
                    `MarkdownNotebook__text-block--${node.type}`,
                    isToolInsertMenuOpen && 'MarkdownNotebook__text-block--insert-placeholder',
                    isAIPromptOpen && 'MarkdownNotebook__text-block--ai-prompt',
                    hasInvalidInsertMenuQuery && 'MarkdownNotebook__text-block--invalid-insert-filter'
                )}
                contentEditable={mode === 'edit' && !isAIThinking}
                suppressContentEditableWarning
                data-placeholder={isEmpty ? placeholder : undefined}
                onInput={handleInput}
                onPaste={handlePaste}
                onBlur={handleBlur}
                onKeyDown={handleKeyDown}
                onMouseDown={startCrossBlockSelection}
                onMouseUp={handleSelectionChange}
                onKeyUp={handleSelectionChange}
            />
        </div>
    )
}

function InsertBoundaryButton({
    boundaryIndex,
    isAvailable,
    isVisible,
    insertEmptyParagraphAtBoundary,
    setActiveBoundaryIndex,
}: {
    boundaryIndex: number
    isAvailable: boolean
    isVisible: boolean
    insertEmptyParagraphAtBoundary: (boundaryIndex: number) => void
    setActiveBoundaryIndex: (boundaryIndex: number) => void
}): JSX.Element {
    return (
        <div className="MarkdownNotebook__insert-boundary" onMouseEnter={() => setActiveBoundaryIndex(boundaryIndex)}>
            {isAvailable ? (
                <LemonButton
                    size="xsmall"
                    icon={<IconPlus />}
                    className={clsx(
                        'MarkdownNotebook__insert-boundary-button',
                        isVisible && 'MarkdownNotebook__insert-boundary-button--visible'
                    )}
                    tooltip="Add block"
                    onClick={() => insertEmptyParagraphAtBoundary(boundaryIndex)}
                    aria-label="Add block"
                    aria-hidden={!isVisible}
                    data-boundary-index={boundaryIndex}
                    tabIndex={isVisible ? 0 : -1}
                />
            ) : null}
        </div>
    )
}

function FormattingToolbar({
    node,
    placement,
    top,
    left,
    applyInlineMark,
    applyInlineLink,
    currentLinkHref,
    initialLinkEditorOpen,
    setBlockStyle,
}: {
    node: NotebookTextBlockNode
    placement: 'above' | 'below'
    top: number
    left: number
    applyInlineMark: (markType: NotebookInlineMark['type']) => void
    applyInlineLink: (href: string | null) => void
    currentLinkHref: string | null
    initialLinkEditorOpen: boolean
    setBlockStyle: (nodeId: string, style: 'paragraph' | 'blockquote' | 1 | 2 | 3) => void
}): JSX.Element {
    const [isLinkEditorOpen, setIsLinkEditorOpen] = useState(initialLinkEditorOpen)
    const [linkHref, setLinkHref] = useState(currentLinkHref ?? '')
    const toolbarStyle = {
        '--markdown-notebook-format-toolbar-top': `${top}px`,
        '--markdown-notebook-format-toolbar-left': `${left}px`,
    } as CSSProperties
    const normalizedLinkHref = sanitizeNotebookLinkHref(linkHref)
    const hasExistingLink = !!currentLinkHref

    useEffect(() => {
        if (initialLinkEditorOpen) {
            setLinkHref(currentLinkHref ?? '')
            setIsLinkEditorOpen(true)
            return
        }

        if (!isLinkEditorOpen) {
            setLinkHref(currentLinkHref ?? '')
        }
    }, [currentLinkHref, initialLinkEditorOpen, isLinkEditorOpen])

    const openLinkEditor = (): void => {
        setLinkHref(currentLinkHref ?? '')
        setIsLinkEditorOpen(true)
    }

    const setLink = (): void => {
        if (!normalizedLinkHref) {
            return
        }

        applyInlineLink(normalizedLinkHref)
        setIsLinkEditorOpen(false)
    }

    const removeLink = (): void => {
        applyInlineLink(null)
        setIsLinkEditorOpen(false)
    }

    return (
        <div
            className={clsx('MarkdownNotebook__format-toolbar', `MarkdownNotebook__format-toolbar--${placement}`)}
            style={toolbarStyle}
            onMouseDown={(event) => {
                if (
                    event.target instanceof HTMLElement &&
                    event.target.closest('.MarkdownNotebook__format-link-editor')
                ) {
                    return
                }
                event.preventDefault()
            }}
        >
            <LemonMenu
                items={[
                    { label: 'Text', onClick: () => setBlockStyle(node.id, 'paragraph') },
                    { label: 'Heading 1', onClick: () => setBlockStyle(node.id, 1) },
                    { label: 'Heading 2', onClick: () => setBlockStyle(node.id, 2) },
                    { label: 'Heading 3', onClick: () => setBlockStyle(node.id, 3) },
                    { label: 'Quote', onClick: () => setBlockStyle(node.id, 'blockquote') },
                ]}
            >
                <LemonButton size="xsmall" tooltip="Text style">
                    {node.type === 'heading' ? `H${node.level ?? 1}` : 'Text'}
                </LemonButton>
            </LemonMenu>
            <LemonButton size="xsmall" icon={<IconBold />} tooltip="Bold" onClick={() => applyInlineMark('bold')} />
            <LemonButton
                size="xsmall"
                icon={<IconItalic />}
                tooltip="Italic"
                onClick={() => applyInlineMark('italic')}
            />
            <LemonButton size="xsmall" tooltip="Underline" onClick={() => applyInlineMark('underline')}>
                <span className="font-semibold underline">U</span>
            </LemonButton>
            <LemonButton
                size="xsmall"
                icon={<IconLink />}
                tooltip="Link"
                aria-label="Link"
                active={hasExistingLink || isLinkEditorOpen}
                onClick={openLinkEditor}
            />
            {isLinkEditorOpen ? (
                <div className="MarkdownNotebook__format-link-editor">
                    <LemonInput
                        size="small"
                        type="url"
                        placeholder="https://..."
                        aria-label="Link URL"
                        value={linkHref}
                        onChange={setLinkHref}
                        onPressEnter={setLink}
                        autoFocus
                        className="MarkdownNotebook__format-link-input"
                    />
                    {hasExistingLink ? (
                        <LemonButton size="xsmall" status="danger" onClick={removeLink}>
                            Remove
                        </LemonButton>
                    ) : null}
                    <LemonButton
                        size="xsmall"
                        type="primary"
                        onClick={setLink}
                        disabledReason={!normalizedLinkHref ? 'Enter an http or https URL' : undefined}
                    >
                        {hasExistingLink ? 'Update' : 'Set'}
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}

function NotebookComponentShell({
    node,
    mode,
    componentPanels,
    isSelected,
    registry,
    toggleComponentPanel,
    setBlockRef,
    updateNode,
    deleteNode,
    insertParagraphAfterNode,
    moveFocusToAdjacentNode,
}: NotebookComponentShellProps): JSX.Element {
    const definition = getMarkdownNotebookComponentDefinition(registry, node.tagName)
    const errors = [...(node.errors ?? []), ...(definition?.validateProps?.(node.props) ?? [])]
    const ViewComponent = definition?.ViewComponent
    const EditComponent = definition?.EditComponent ?? definition?.ViewComponent
    const showEditPanel = mode === 'edit' && componentPanels.edit
    const showViewPanel =
        (mode === 'view' || componentPanels.view) && !(showEditPanel && definition?.exclusiveEditPanel)
    const titleDisplay = getComponentTitleDisplay(node, definition)
    const updateProps = (props: Partial<NotebookComponentProps>): void => {
        const nextProps = Object.entries(props).reduce<NotebookComponentProps>((accumulator, [key, value]) => {
            if (value !== undefined) {
                accumulator[key] = value
            }
            return accumulator
        }, {})

        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'component') {
                return currentNode
            }
            return {
                ...currentNode,
                props: {
                    ...currentNode.props,
                    ...nextProps,
                },
            }
        })
    }
    const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
        if (mode !== 'edit' || event.target !== event.currentTarget) {
            return
        }

        if (event.key === 'Backspace') {
            event.preventDefault()
            deleteNode()
            return
        }

        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            if (moveFocusToAdjacentNode(node.id, event.key === 'ArrowDown' ? 'next' : 'previous', 0)) {
                event.preventDefault()
                return
            }
        }

        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            insertParagraphAfterNode()
        }
    }

    return (
        <div
            className={clsx(
                'MarkdownNotebook__component-shell',
                isSelected && 'MarkdownNotebook__component-shell--selected',
                errors.length && 'MarkdownNotebook__component-shell--error'
            )}
            ref={setBlockRef}
            tabIndex={mode === 'edit' ? 0 : undefined}
            onKeyDown={handleKeyDown}
        >
            <div className="MarkdownNotebook__component-toolbar">
                <div className="MarkdownNotebook__component-toolbar-left">
                    <div
                        className={clsx(
                            'MarkdownNotebook__component-title',
                            `MarkdownNotebook__component-title--${titleDisplay.tone}`
                        )}
                    >
                        {titleDisplay.icon ? (
                            <span className="MarkdownNotebook__component-title-icon">{titleDisplay.icon}</span>
                        ) : null}
                        <span>{titleDisplay.label}</span>
                    </div>
                    {mode === 'edit' ? (
                        <div className="MarkdownNotebook__component-mode-actions">
                            <LemonButton
                                aria-label="Edit mode"
                                size="xsmall"
                                icon={<IconPencil />}
                                active={componentPanels.edit}
                                tooltip="Edit mode"
                                onClick={() => toggleComponentPanel('edit')}
                            />
                            <LemonButton
                                aria-label="View mode"
                                size="xsmall"
                                icon={<IconEye />}
                                active={componentPanels.view}
                                tooltip="View mode"
                                onClick={() => toggleComponentPanel('view')}
                            />
                        </div>
                    ) : null}
                </div>
                {mode === 'edit' ? (
                    <div className="MarkdownNotebook__component-actions">
                        <LemonButton
                            aria-label="Delete component"
                            size="xsmall"
                            icon={<IconTrash />}
                            tooltip="Delete"
                            status="danger"
                            onClick={deleteNode}
                        />
                    </div>
                ) : null}
            </div>
            {errors.length ? (
                <div className="MarkdownNotebook__component-errors">
                    {errors.map((error) => (
                        <div key={error}>{error}</div>
                    ))}
                </div>
            ) : null}
            {showEditPanel && EditComponent ? (
                <div className="MarkdownNotebook__component-panel">
                    <EditComponent node={node} mode="edit" updateProps={updateProps} />
                </div>
            ) : null}
            {showViewPanel ? (
                <div className="MarkdownNotebook__component-panel">
                    {ViewComponent ? (
                        <ViewComponent node={node} mode="view" updateProps={updateProps} />
                    ) : (
                        <pre>{JSON.stringify(node.props, null, 2)}</pre>
                    )}
                </div>
            ) : null}
        </div>
    )
}

const MemoizedNotebookComponentShell = memo(NotebookComponentShell, areNotebookComponentShellPropsEqual)

function areNotebookComponentShellPropsEqual(
    previousProps: NotebookComponentShellProps,
    nextProps: NotebookComponentShellProps
): boolean {
    const previousDefinition = getMarkdownNotebookComponentDefinition(
        previousProps.registry,
        previousProps.node.tagName
    )
    const nextDefinition = getMarkdownNotebookComponentDefinition(nextProps.registry, nextProps.node.tagName)

    return (
        previousProps.mode === nextProps.mode &&
        previousProps.updateNode === nextProps.updateNode &&
        previousProps.moveFocusToAdjacentNode === nextProps.moveFocusToAdjacentNode &&
        previousDefinition === nextDefinition &&
        previousProps.node.id === nextProps.node.id &&
        previousProps.isSelected === nextProps.isSelected &&
        previousProps.componentPanels.view === nextProps.componentPanels.view &&
        previousProps.componentPanels.edit === nextProps.componentPanels.edit &&
        getNodeFingerprint(previousProps.node) === getNodeFingerprint(nextProps.node)
    )
}

function getComponentTitleDisplay(
    node: NotebookComponentBlockNode,
    definition: NotebookComponentDefinition | null
): ComponentTitleDisplay {
    if (node.tagName === 'Query') {
        return getQueryComponentTitleDisplay(node, definition)
    }

    const label = definition?.label ?? node.tagName
    const tone = getComponentTitleTone(node.tagName, definition?.category)

    return {
        label,
        tone,
        icon: definition?.icon ?? getComponentTitleFallbackIcon(tone),
    }
}

function getQueryComponentTitleDisplay(
    node: NotebookComponentBlockNode,
    definition: NotebookComponentDefinition | null
): ComponentTitleDisplay {
    const query = getNotebookObjectProp(node.props.query)
    const source = getNotebookObjectProp(query?.source)
    const queryKind = getNotebookStringProp(query?.kind)
    const sourceKind = getNotebookStringProp(source?.kind)

    if (sourceKind === 'HogQLQuery') {
        return { label: 'SQL', tone: 'sql', icon: <IconDatabase /> }
    }
    if (sourceKind === 'FunnelsQuery') {
        return { label: 'Funnel', tone: 'insight', icon: <IconGraph /> }
    }
    if (sourceKind === 'TrendsQuery') {
        return { label: 'Trend', tone: 'insight', icon: <IconGraph /> }
    }
    if (queryKind === 'SavedInsightNode') {
        return { label: 'Saved insight', tone: 'insight', icon: <IconGraph /> }
    }
    if (sourceKind === 'EventsQuery') {
        return { label: 'Events', tone: 'data', icon: <IconList /> }
    }

    return {
        label: definition?.label ?? node.tagName,
        tone: 'insight',
        icon: definition?.icon ?? <IconGraph />,
    }
}

function getComponentTitleTone(tagName: string, category: string | undefined): ComponentTitleTone {
    if (tagName === 'Experiment') {
        return 'experiment'
    }

    if (tagName === 'DuckSQL' || tagName === 'HogQLSQL') {
        return 'sql'
    }

    if (category === 'Insight') {
        return 'insight'
    }
    if (category === 'Code') {
        return 'code'
    }
    if (category === 'Data') {
        return 'data'
    }
    if (category === 'Media') {
        return 'media'
    }
    if (category === 'PostHog') {
        return 'posthog'
    }
    return 'default'
}

function getComponentTitleFallbackIcon(tone: ComponentTitleTone): ReactNode {
    if (tone === 'sql') {
        return <IconDatabase />
    }
    if (tone === 'insight' || tone === 'experiment') {
        return <IconGraph />
    }
    if (tone === 'data' || tone === 'media') {
        return <IconList />
    }
    return null
}

function getNotebookObjectProp(value: NotebookPropValue | undefined): Record<string, NotebookPropValue> | undefined {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return undefined
    }
    return value
}

function getNotebookStringProp(value: NotebookPropValue | undefined): string | undefined {
    return typeof value === 'string' ? value : undefined
}

function InsertMenu({
    query,
    commands,
    targetNodeId,
    position,
    selectedIndex,
    onClose,
}: {
    query: string
    commands: InsertCommand[]
    targetNodeId: string
    position: InsertMenuPosition | null
    selectedIndex: number
    onClose: () => void
}): JSX.Element {
    const filteredCommands = getFilteredInsertCommands(commands, query)
    const commandsByCategory = groupInsertCommandsByCategory(filteredCommands)
    const selectedCommandKey =
        filteredCommands[getClampedInsertMenuSelectedIndex(selectedIndex, filteredCommands.length)]?.key
    const menuStyle = position
        ? ({
              '--markdown-notebook-insert-menu-left': `${position.left}px`,
              '--markdown-notebook-insert-menu-max-height': `${position.maxHeight}px`,
              '--markdown-notebook-insert-menu-top': `${position.top}px`,
              '--markdown-notebook-insert-menu-width': `${position.width}px`,
          } as CSSProperties)
        : undefined

    return (
        <div
            className={clsx(
                'MarkdownNotebook__insert-menu',
                position && 'MarkdownNotebook__insert-menu--positioned',
                position && `MarkdownNotebook__insert-menu--${position.placement}`
            )}
            style={menuStyle}
        >
            {Object.entries(commandsByCategory).map(([category, categoryCommands]) => (
                <div className="MarkdownNotebook__insert-category" key={category}>
                    <h5>{category}</h5>
                    <div className="MarkdownNotebook__insert-grid">
                        {categoryCommands.map((command) => (
                            <button
                                className={clsx(
                                    'MarkdownNotebook__insert-item',
                                    command.key === selectedCommandKey && 'MarkdownNotebook__insert-item--selected'
                                )}
                                key={command.key}
                                aria-selected={command.key === selectedCommandKey}
                                type="button"
                                onClick={() => {
                                    command.run(targetNodeId)
                                    if (command.closeOnRun !== false) {
                                        onClose()
                                    }
                                }}
                            >
                                {command.icon ? (
                                    <span className="MarkdownNotebook__insert-item-icon">{command.icon}</span>
                                ) : null}
                                <span>{renderHighlightedInsertCommandLabel(command.label, query)}</span>
                            </button>
                        ))}
                    </div>
                </div>
            ))}
            {!filteredCommands.length ? <div className="MarkdownNotebook__empty-menu">No components found</div> : null}
        </div>
    )
}

function renderHighlightedInsertCommandLabel(label: string, query: string): ReactNode {
    const normalizedQuery = query.trim().toLowerCase()
    const matchIndex = normalizedQuery ? label.toLowerCase().indexOf(normalizedQuery) : -1
    if (matchIndex === -1) {
        return label
    }

    const matchEndIndex = matchIndex + normalizedQuery.length
    return (
        <>
            {label.slice(0, matchIndex)}
            <mark className="MarkdownNotebook__insert-item-highlight">{label.slice(matchIndex, matchEndIndex)}</mark>
            {label.slice(matchEndIndex)}
        </>
    )
}

function getFilteredInsertCommands(commands: InsertCommand[], query: string): InsertCommand[] {
    const normalizedQuery = query.trim().toLowerCase()
    if (!normalizedQuery) {
        return commands
    }

    return commands.filter((command) => getInsertCommandSearchText(command).includes(normalizedQuery))
}

function getInsertCommandSearchText(command: InsertCommand): string {
    return `${command.label} ${command.category} ${command.description ?? ''} ${(command.aliases ?? []).join(' ')}`
        .trim()
        .toLowerCase()
}

function groupInsertCommandsByCategory(commands: InsertCommand[]): Record<string, InsertCommand[]> {
    return commands.reduce<Record<string, InsertCommand[]>>((accumulator, command) => {
        accumulator[command.category] = [...(accumulator[command.category] ?? []), command]
        return accumulator
    }, {})
}

function getClampedInsertMenuSelectedIndex(selectedIndex: number, commandCount: number): number {
    if (commandCount <= 0) {
        return 0
    }
    return Math.max(0, Math.min(selectedIndex, commandCount - 1))
}

function getNextInsertMenuSelectedIndex(
    selectedIndex: number,
    commandCount: number,
    direction: InsertMenuSelectionDirection
): number {
    if (commandCount <= 0) {
        return 0
    }

    const clampedIndex = getClampedInsertMenuSelectedIndex(selectedIndex, commandCount)
    return direction === 'next' ? (clampedIndex + 1) % commandCount : (clampedIndex - 1 + commandCount) % commandCount
}

function buildInsertCommands(
    registry: NotebookComponentRegistry,
    replaceNodeWithInsertedComponent: (nodeId: string, nextNode: NotebookComponentBlockNode) => void,
    replaceNode: (nodeId: string, nextNode: NotebookBlockNode) => void,
    focusInsertedTable: (nodeId: string) => void,
    openAIPrompt?: (nodeId: string) => void
): InsertCommand[] {
    const insertComponent = (targetNodeId: string, tagName: string, props: NotebookComponentProps): void => {
        const node: NotebookComponentBlockNode = {
            id: makeEmptyParagraph(`component-${tagName}`).id,
            type: 'component',
            tagName,
            props,
        }

        replaceNodeWithInsertedComponent(targetNodeId, node)
    }

    const insertRegisteredComponent = (targetNodeId: string, tagName: string, props?: NotebookComponentProps): void => {
        const definition = registry.components[tagName]
        if (!definition) {
            return
        }

        insertComponent(
            targetNodeId,
            tagName,
            props ??
                (typeof definition.defaultProps === 'function'
                    ? definition.defaultProps()
                    : (definition.defaultProps ?? {}))
        )
    }

    const insertTable = (targetNodeId: string): void => {
        const nodeId = makeEmptyParagraph('table').id
        replaceNode(targetNodeId, {
            id: nodeId,
            type: 'table',
            headers: [
                { children: [{ type: 'text', text: 'Column 1' }] },
                { children: [{ type: 'text', text: 'Column 2' }] },
            ],
            rows: [[{ children: [] }, { children: [] }]],
        })
        focusInsertedTable(nodeId)
    }

    const aiCommands: InsertCommand[] = openAIPrompt
        ? [
              {
                  key: 'ai-ask',
                  label: 'Ask PostHog AI',
                  category: 'AI',
                  description: 'Ask PostHog AI to write or edit this notebook',
                  aliases: ['ai', 'ask', 'posthog ai'],
                  icon: <IconSparkles />,
                  closeOnRun: false,
                  run: openAIPrompt,
              },
          ]
        : []

    const queryCommands: InsertCommand[] = [
        {
            key: 'query-trend',
            label: 'Trend',
            category: 'Insight',
            icon: <IconGraph />,
            run: (targetNodeId) =>
                insertComponent(targetNodeId, 'Query', {
                    query: {
                        kind: 'InsightVizNode',
                        source: { kind: 'TrendsQuery', series: [{ event: '$pageview', kind: 'EventsNode' }] },
                    },
                }),
        },
        {
            key: 'query-funnel',
            label: 'Funnel',
            category: 'Insight',
            icon: <IconGraph />,
            run: (targetNodeId) =>
                insertComponent(targetNodeId, 'Query', {
                    query: {
                        kind: 'InsightVizNode',
                        source: {
                            kind: 'FunnelsQuery',
                            series: [
                                { event: '$pageview', kind: 'EventsNode' },
                                { event: '$pageleave', kind: 'EventsNode' },
                            ],
                        },
                    },
                }),
        },
        {
            key: 'query-saved-insight',
            label: 'Saved insight',
            category: 'Insight',
            icon: <IconGraph />,
            run: (targetNodeId) =>
                insertComponent(targetNodeId, 'Query', {
                    query: {
                        kind: 'SavedInsightNode',
                        shortId: '',
                    },
                }),
        },
        {
            key: 'query-sql',
            label: 'SQL',
            category: 'SQL',
            icon: <IconDatabase />,
            run: (targetNodeId) =>
                insertComponent(targetNodeId, 'Query', {
                    query: {
                        kind: 'DataTableNode',
                        source: { kind: 'HogQLQuery', query: 'select event, count() from events group by event' },
                    },
                }),
        },
    ]

    const dataCommands: InsertCommand[] = [
        {
            key: 'query-events',
            label: 'Events',
            category: 'Data',
            icon: <IconList />,
            run: (targetNodeId) =>
                insertComponent(targetNodeId, 'Query', {
                    query: {
                        kind: 'DataTableNode',
                        source: { kind: 'EventsQuery', select: ['*', 'event', 'person', 'timestamp'] },
                    },
                }),
        },
        {
            key: 'data-people',
            label: 'People',
            category: 'Data',
            icon: <IconList />,
            run: (targetNodeId) => insertRegisteredComponent(targetNodeId, 'Person'),
        },
        {
            key: 'data-session-recordings',
            label: 'Session recordings',
            category: 'Data',
            icon: <IconList />,
            run: (targetNodeId) => insertRegisteredComponent(targetNodeId, 'RecordingPlaylist'),
        },
    ]

    const experimentCommands: InsertCommand[] = [
        {
            key: 'experiment',
            label: 'Experiment',
            category: 'Experiment',
            icon: <IconGraph />,
            run: (targetNodeId) => insertRegisteredComponent(targetNodeId, 'Experiment'),
        },
    ]

    const mediaCommands: InsertCommand[] = [
        {
            key: 'media-image',
            label: 'Image',
            category: 'Media',
            icon: <IconList />,
            run: (targetNodeId) => insertRegisteredComponent(targetNodeId, 'Image'),
        },
        {
            key: 'media-table',
            label: 'Table',
            category: 'Media',
            icon: <IconList />,
            run: insertTable,
        },
        {
            key: 'media-iframe',
            label: 'Iframe',
            category: 'Media',
            icon: <IconList />,
            run: (targetNodeId) => insertRegisteredComponent(targetNodeId, 'Embed'),
        },
        {
            key: 'media-latex',
            label: 'LaTeX',
            category: 'Media',
            icon: <IconList />,
            run: (targetNodeId) => insertRegisteredComponent(targetNodeId, 'Latex'),
        },
    ]

    const textCommands: InsertCommand[] = [
        {
            key: 'text-heading-1',
            label: 'Heading 1',
            category: 'Text',
            aliases: ['h1'],
            icon: <IconPencil />,
            run: (targetNodeId) =>
                replaceNode(targetNodeId, {
                    id: targetNodeId,
                    type: 'heading',
                    level: 1,
                    children: [],
                }),
        },
        {
            key: 'text-heading-2',
            label: 'Heading 2',
            category: 'Text',
            aliases: ['h2'],
            icon: <IconPencil />,
            run: (targetNodeId) =>
                replaceNode(targetNodeId, {
                    id: targetNodeId,
                    type: 'heading',
                    level: 2,
                    children: [],
                }),
        },
        {
            key: 'text-heading-3',
            label: 'Heading 3',
            category: 'Text',
            aliases: ['h3'],
            icon: <IconPencil />,
            run: (targetNodeId) =>
                replaceNode(targetNodeId, {
                    id: targetNodeId,
                    type: 'heading',
                    level: 3,
                    children: [],
                }),
        },
    ]

    return [...aiCommands, ...queryCommands, ...dataCommands, ...experimentCommands, ...mediaCommands, ...textCommands]
}

function isTextBlockNode(node: NotebookBlockNode): node is NotebookTextBlockNode {
    return node.type === 'paragraph' || node.type === 'heading' || node.type === 'blockquote'
}

function isInlineInsertMenuRow(node: NotebookBlockNode | undefined, insertMenuNodeId?: string): boolean {
    if (!node || !isTextBlockNode(node)) {
        return false
    }

    if (node.id === insertMenuNodeId) {
        return true
    }

    const text = getInlineText(node.children)
    return !text.trim() || getSlashCommandQuery(text) !== null
}

function isBlankInsertMenuButtonRow(node: NotebookBlockNode | undefined): boolean {
    if (!node || !isTextBlockNode(node)) {
        return false
    }

    return !getInlineText(node.children).trim()
}

function getInlineInsertMenuQuery(node: NotebookBlockNode): string {
    if (!isTextBlockNode(node)) {
        return ''
    }

    return getSlashCommandQuery(getInlineText(node.children)) ?? ''
}

function getListItemRefKey(nodeId: string, itemIndex: number): string {
    return `${nodeId}:${String(itemIndex)}`
}

function buildRenderedListItems(items: NotebookListItem[]): RenderedListItem[] {
    const rootItems: RenderedListItem[] = []
    const stack: RenderedListItem[] = []

    items.forEach((item, index) => {
        const renderedItem: RenderedListItem = {
            ...item,
            depth: Math.max(0, item.depth),
            index,
            childrenItems: [],
        }
        while (stack.length && renderedItem.depth <= stack[stack.length - 1].depth) {
            stack.pop()
        }

        const parent = stack[stack.length - 1]
        if (parent) {
            parent.childrenItems.push(renderedItem)
        } else {
            rootItems.push(renderedItem)
        }
        stack.push(renderedItem)
    })

    return rootItems
}

function getListItemSubtreeEndIndex(items: NotebookListItem[], itemIndex: number): number {
    const item = items[itemIndex]
    if (!item) {
        return itemIndex
    }

    let nextIndex = itemIndex + 1
    while (nextIndex < items.length && items[nextIndex].depth > item.depth) {
        nextIndex += 1
    }
    return nextIndex
}

function getTableCellRefKey(nodeId: string, position: TableCellPosition): string {
    return `${nodeId}:${position.section}:${String(position.rowIndex)}:${String(position.columnIndex)}`
}

function getTableColumnCount(node: NotebookTableBlockNode): number {
    return Math.max(1, node.headers.length, node.alignments?.length ?? 0, ...node.rows.map((row) => row.length))
}

function normalizeTableRow(row: NotebookTableCell[], columnCount: number): NotebookTableCell[] {
    return Array.from({ length: columnCount }, (_, index) => row[index] ?? { children: [] })
}

function makeEmptyTableRow(columnCount: number): NotebookTableCell[] {
    return Array.from({ length: columnCount }, () => ({ children: [] }))
}

function getTableCellPositions(node: NotebookTableBlockNode): TableCellPosition[] {
    const columnCount = getTableColumnCount(node)
    return [
        ...Array.from({ length: columnCount }, (_, columnIndex) => ({
            section: 'header' as const,
            rowIndex: 0,
            columnIndex,
        })),
        ...node.rows.flatMap((_, rowIndex) =>
            Array.from({ length: columnCount }, (_, columnIndex) => ({
                section: 'body' as const,
                rowIndex,
                columnIndex,
            }))
        ),
    ]
}

function getTableEdgeCellPosition(
    node: NotebookTableBlockNode,
    direction: InsertMenuSelectionDirection
): TableCellPosition | null {
    const positions = getTableCellPositions(node)
    return direction === 'next' ? (positions[0] ?? null) : (positions[positions.length - 1] ?? null)
}

function getTableCellAtPosition(
    node: NotebookTableBlockNode,
    position: TableCellPosition
): NotebookTableCell | undefined {
    if (position.section === 'header') {
        return node.headers[position.columnIndex]
    }
    return node.rows[position.rowIndex]?.[position.columnIndex]
}

function tableCellPositionsEqual(left: TableCellPosition, right: TableCellPosition): boolean {
    return left.section === right.section && left.rowIndex === right.rowIndex && left.columnIndex === right.columnIndex
}

function getSlashCommandQuery(text: string): string | null {
    const trimmedText = text.trimStart()
    return trimmedText.startsWith('/') ? trimmedText.slice(1) : null
}

function getListShortcut(text: string): { ordered: boolean } | null {
    if (/^\d+[.)]\s?$/.test(text)) {
        return { ordered: true }
    }

    if (/^[-*+•]\s$/.test(text)) {
        return { ordered: false }
    }

    return null
}

function getHeadingShortcut(text: string, currentLevel: number | null): 1 | 2 | 3 | null {
    if (!/^#{1,3}\s?$/.test(text)) {
        return null
    }

    const markerLevel = text.trim().length
    const nextLevel = currentLevel === null ? markerLevel : currentLevel + markerLevel

    return Math.min(3, Math.max(1, nextLevel)) as 1 | 2 | 3
}

function getBlockquoteShortcut(text: string): boolean {
    return /^>\s?$/.test(text)
}

function isInsertBoundaryAvailable(
    nodes: NotebookBlockNode[],
    boundaryIndex: number,
    insertMenuNodeId?: string
): boolean {
    return (
        !isInlineInsertMenuRow(nodes[boundaryIndex - 1], insertMenuNodeId) &&
        !isInlineInsertMenuRow(nodes[boundaryIndex], insertMenuNodeId)
    )
}

function isInsertBoundaryVisible(
    nodes: NotebookBlockNode[],
    boundaryIndex: number,
    activeBoundaryIndex: number | null,
    focusedRowIndex: number | null,
    insertMenuNodeId?: string
): boolean {
    if (
        activeBoundaryIndex === null ||
        focusedRowIndex !== null ||
        insertMenuNodeId !== undefined ||
        !isInsertBoundaryAvailable(nodes, boundaryIndex, insertMenuNodeId)
    ) {
        return false
    }

    return boundaryIndex === activeBoundaryIndex
}

function getClosestInsertBoundaryIndex(rowElement: HTMLElement, rowIndex: number, clientY: number): number {
    const rowRect = rowElement.getBoundingClientRect()

    if (rowRect.height <= 0) {
        return rowIndex
    }

    return clientY <= rowRect.top + rowRect.height / 2 ? rowIndex : rowIndex + 1
}

function ensureEditableTrailingParagraph(document: NotebookDocument): NotebookDocument {
    const lastNode = document.nodes[document.nodes.length - 1]
    if (lastNode?.type !== 'component') {
        return document
    }

    return {
        ...document,
        nodes: [...document.nodes, makeEmptyParagraph(`after-${lastNode.id}`)],
    }
}

function areNotebookDocumentsEqual(left: NotebookDocument, right: NotebookDocument): boolean {
    return JSON.stringify(left) === JSON.stringify(right)
}

function getHistoryRestoreSelection(document: NotebookDocument): RestoreSelectionRequest | null {
    for (const node of document.nodes) {
        if (isTextBlockNode(node)) {
            const offset = getInlineText(node.children).length
            return { nodeId: node.id, start: offset, end: offset }
        }

        if (node.type === 'list' && node.items[0]) {
            const offset = getInlineText(node.items[0].children).length
            return { nodeId: node.id, listItemIndex: 0, start: offset, end: offset }
        }

        if (node.type === 'table') {
            const firstPosition = getTableEdgeCellPosition(node, 'next')
            const cell = firstPosition ? getTableCellAtPosition(node, firstPosition) : undefined
            if (firstPosition) {
                const offset = getInlineText(cell?.children ?? []).length
                return { nodeId: node.id, tableCell: firstPosition, start: offset, end: offset }
            }
        }

        if (node.type === 'component') {
            return { nodeId: node.id, start: 0, end: 0 }
        }
    }

    return null
}

function hasNotebookContent(nodes: NotebookBlockNode[]): boolean {
    return nodes.some(nodeHasContent)
}

function nodeHasContent(node: NotebookBlockNode): boolean {
    if (isTextBlockNode(node)) {
        return getInlineText(node.children).trim().length > 0
    }
    if (node.type === 'list') {
        return node.items.some((item) => getInlineText(item.children).trim().length > 0)
    }
    if (node.type === 'table') {
        return [...node.headers, ...node.rows.flat()].some((cell) => getInlineText(cell.children).trim().length > 0)
    }
    if (node.type === 'code') {
        return node.text.trim().length > 0
    }
    return true
}

function getElementLineHeight(element: HTMLElement): number {
    const styles = window.getComputedStyle(element)
    const lineHeight = Number.parseFloat(styles.lineHeight)
    if (Number.isFinite(lineHeight)) {
        return lineHeight
    }

    const fontSize = Number.parseFloat(styles.fontSize)
    return Number.isFinite(fontSize) ? fontSize * 1.55 : 24
}

function getInsertMenuPosition(anchorElement: HTMLElement): InsertMenuPosition {
    const anchorRect = anchorElement.getBoundingClientRect()
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight
    const availableViewportWidth = Math.max(0, viewportWidth - INSERT_MENU_VIEWPORT_PADDING * 2)
    const width = Math.min(INSERT_MENU_WIDTH, availableViewportWidth)
    const maxLeft = viewportWidth - INSERT_MENU_VIEWPORT_PADDING - width
    const left = Math.min(
        Math.max(INSERT_MENU_VIEWPORT_PADDING, anchorRect.left),
        Math.max(INSERT_MENU_VIEWPORT_PADDING, maxLeft)
    )
    const availableBelow = Math.max(
        0,
        viewportHeight - anchorRect.bottom - INSERT_MENU_GAP - INSERT_MENU_VIEWPORT_PADDING
    )
    const availableAbove = Math.max(0, anchorRect.top - INSERT_MENU_GAP - INSERT_MENU_VIEWPORT_PADDING)
    const placement = availableBelow >= INSERT_MENU_MIN_HEIGHT || availableBelow >= availableAbove ? 'below' : 'above'
    const availableHeight = placement === 'below' ? availableBelow : availableAbove

    return {
        placement,
        top: placement === 'below' ? anchorRect.bottom + INSERT_MENU_GAP : anchorRect.top - INSERT_MENU_GAP,
        left,
        width,
        maxHeight: Math.min(INSERT_MENU_MAX_HEIGHT, availableHeight),
    }
}

function getSelectionRange(element: HTMLElement, nodeId: string): NotebookTextSelectionRange | null {
    const selection = window.getSelection()
    if (!selection || selection.rangeCount === 0) {
        return null
    }

    const range = selection.getRangeAt(0)
    if (!element.contains(range.commonAncestorContainer) && !rangeIntersectsNode(range, element)) {
        return null
    }
    const textLength = element.textContent?.length ?? 0

    return {
        nodeId,
        start: element.contains(range.startContainer)
            ? getTextOffset(element, range.startContainer, range.startOffset)
            : 0,
        end: element.contains(range.endContainer)
            ? getTextOffset(element, range.endContainer, range.endOffset)
            : textLength,
    }
}

function getSelectionClientRect(range: Range): DOMRect | null {
    if (typeof range.getBoundingClientRect !== 'function') {
        return null
    }

    const rect = range.getBoundingClientRect()
    if (rect.width || rect.height) {
        return rect
    }

    return typeof range.getClientRects === 'function' ? (range.getClientRects()[0] ?? null) : null
}

function getCollapsedSelectionRange(element: HTMLElement, nodeId: string): NotebookTextSelectionRange | null {
    const range = getSelectionRange(element, nodeId)
    if (!range) {
        return null
    }
    return { nodeId, start: range.end, end: range.end }
}

function getTextOffset(root: HTMLElement, container: Node, offset: number): number {
    const range = document.createRange()
    range.selectNodeContents(root)
    range.setEnd(container, offset)
    return range.toString().length
}

function restoreSelection(element: HTMLElement, start: number, end: number): void {
    const selection = window.getSelection()
    if (!selection) {
        return
    }

    const range = document.createRange()
    const startPosition = findTextPosition(element, start)
    const endPosition = findTextPosition(element, end)
    range.setStart(startPosition.node, startPosition.offset)
    range.setEnd(endPosition.node, endPosition.offset)
    selection.removeAllRanges()
    selection.addRange(range)
}

function getNotebookBlockCaretRangeFromPoint(
    clientX: number,
    clientY: number,
    notebookElement: HTMLElement
): Range | null {
    const range = getCaretRangeFromPoint(clientX, clientY)
    if (range) {
        const element = getElementForNode(range.startContainer)
        const editableTextElement = getClosestEditableBlockElement(element)
        if (editableTextElement && notebookElement.contains(editableTextElement)) {
            return range
        }
    }

    const pointedElement = document.elementFromPoint(clientX, clientY)
    const blockElement = pointedElement?.closest(NOTEBOOK_SELECTABLE_BLOCK_SELECTOR)
    if (!blockElement || !notebookElement.contains(blockElement)) {
        return null
    }

    const blockRect = blockElement.getBoundingClientRect()
    const blockRange = document.createRange()
    if (clientY < blockRect.top + blockRect.height / 2) {
        blockRange.setStartBefore(blockElement)
    } else {
        blockRange.setStartAfter(blockElement)
    }
    blockRange.collapse(true)
    return blockRange
}

function getCaretRangeFromPoint(clientX: number, clientY: number): Range | null {
    const caretDocument = document as Document & {
        caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null
        caretRangeFromPoint?: (x: number, y: number) => Range | null
    }
    const caretPosition = caretDocument.caretPositionFromPoint?.(clientX, clientY)
    if (caretPosition) {
        const range = document.createRange()
        range.setStart(caretPosition.offsetNode, caretPosition.offset)
        range.collapse(true)
        return range
    }

    return caretDocument.caretRangeFromPoint?.(clientX, clientY) ?? null
}

function getElementForNode(node: Node): Element | null {
    return node instanceof Element ? node : node.parentElement
}

function getClosestEditableBlockElement(element: Element | null): HTMLElement | null {
    const editableElement = element?.closest(NOTEBOOK_EDITABLE_BLOCK_SELECTOR)
    return editableElement instanceof HTMLElement ? editableElement : null
}

function getEditableBlockElementForRange(range: Range): HTMLElement | null {
    return getClosestEditableBlockElement(getElementForNode(range.startContainer))
}

function selectBetweenRanges(anchorRange: Range, focusRange: Range): void {
    const selection = window.getSelection()
    if (!selection) {
        return
    }

    const range = document.createRange()
    if (anchorRange.compareBoundaryPoints(Range.START_TO_START, focusRange) <= 0) {
        range.setStart(anchorRange.startContainer, anchorRange.startOffset)
        range.setEnd(focusRange.startContainer, focusRange.startOffset)
    } else {
        range.setStart(focusRange.startContainer, focusRange.startOffset)
        range.setEnd(anchorRange.startContainer, anchorRange.startOffset)
    }

    selection.removeAllRanges()
    selection.addRange(range)
}

function getSelectedNotebookMarkdown(
    selection: Selection | null,
    notebookElement: HTMLElement,
    nodes: NotebookBlockNode[],
    blockRefs: Record<string, HTMLElement | null>,
    listItemRefs: Record<string, HTMLElement | null>
): string | null {
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        return null
    }

    const range = selection.getRangeAt(0)
    if (!rangeIntersectsNode(range, notebookElement)) {
        return null
    }

    const selectedNodes: NotebookBlockNode[] = []
    nodes.forEach((node) => {
        const element = blockRefs[node.id]
        if (!element || !rangeIntersectsNode(range, element)) {
            return
        }

        if (isTextBlockNode(node)) {
            const selectedTextNode = getSelectedTextBlockNode(node, element, range)
            if (selectedTextNode) {
                selectedNodes.push(selectedTextNode)
            }
            return
        }

        if (node.type === 'list') {
            const selectedListNode = getSelectedListBlockNode(node, range, listItemRefs)
            if (selectedListNode) {
                selectedNodes.push(selectedListNode)
            }
            return
        }

        if (node.type === 'table') {
            selectedNodes.push(node)
            return
        }

        selectedNodes.push(node)
    })

    if (!selectedNodes.length) {
        return null
    }

    return serializeNotebookNodes(selectedNodes)
}

function serializeNotebookNodes(nodes: NotebookBlockNode[]): string {
    return serializeMarkdownNotebook({ type: 'doc', nodes, errors: [] })
}

function setClipboardMarkdown(clipboardData: DataTransfer, markdown: string): void {
    clipboardData.setData('text/plain', markdown)
    clipboardData.setData('text/markdown', markdown)
}

function getClipboardMarkdown(clipboardData: DataTransfer): string {
    return clipboardData.getData('text/markdown') || clipboardData.getData('text/plain')
}

function getSelectedComponentNodeIds(
    selection: Selection | null,
    nodes: NotebookBlockNode[],
    blockRefs: Record<string, HTMLElement | null>
): Set<string> {
    const selectedComponentNodeIds = new Set<string>()
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        return selectedComponentNodeIds
    }

    const range = selection.getRangeAt(0)
    nodes.forEach((node) => {
        if (node.type !== 'component') {
            return
        }

        const element = blockRefs[node.id]
        if (!element || !rangeIntersectsNode(range, element) || isSelectionInsideElement(selection, element)) {
            return
        }

        selectedComponentNodeIds.add(node.id)
    })

    return selectedComponentNodeIds
}

function setsEqual(left: Set<string>, right: Set<string>): boolean {
    if (left.size !== right.size) {
        return false
    }

    for (const value of left) {
        if (!right.has(value)) {
            return false
        }
    }

    return true
}

function writeSystemClipboardText(markdown: string): void {
    if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
        return
    }

    void navigator.clipboard.writeText(markdown).catch(() => {})
}

async function readSystemClipboardText(): Promise<string | null> {
    if (typeof navigator === 'undefined' || !navigator.clipboard?.readText) {
        return null
    }

    try {
        return await navigator.clipboard.readText()
    } catch {
        return null
    }
}

function getFocusedComponentNode(
    element: Element | null,
    nodes: NotebookBlockNode[],
    blockRefs: Record<string, HTMLElement | null>
): NotebookComponentBlockNode | null {
    if (!(element instanceof HTMLElement)) {
        return null
    }

    return (
        nodes.find(
            (node): node is NotebookComponentBlockNode => node.type === 'component' && blockRefs[node.id] === element
        ) ?? null
    )
}

function getComponentNodeForSelection(
    selection: Selection | null,
    nodes: NotebookBlockNode[],
    blockRefs: Record<string, HTMLElement | null>
): NotebookComponentBlockNode | null {
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        return null
    }

    return (
        nodes.find((node): node is NotebookComponentBlockNode => {
            if (node.type !== 'component') {
                return false
            }

            const element = blockRefs[node.id]
            return !!element && isSelectionInsideElement(selection, element)
        }) ?? null
    )
}

function isSelectionInsideElement(selection: Selection | null, element: HTMLElement): boolean {
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        return false
    }

    const range = selection.getRangeAt(0)
    return element.contains(range.startContainer) && element.contains(range.endContainer)
}

function getSelectedTextBlockNode(
    node: NotebookTextBlockNode,
    element: HTMLElement,
    range: Range
): NotebookTextBlockNode | null {
    const selectedChildren = getSelectedInlineNodes(node.children, element, range)

    if (!selectedChildren.length) {
        return null
    }

    return { ...node, children: selectedChildren }
}

function getSelectedListBlockNode(
    node: NotebookListBlockNode,
    range: Range,
    listItemRefs: Record<string, HTMLElement | null>
): NotebookListBlockNode | null {
    const selectedItems = node.items.flatMap((item, index) => {
        const element = listItemRefs[getListItemRefKey(node.id, index)]
        if (!element || !rangeIntersectsNode(range, element)) {
            return []
        }

        const selectedChildren = getSelectedInlineNodes(item.children, element, range)
        return selectedChildren.length ? [{ ...item, children: selectedChildren }] : []
    })

    if (!selectedItems.length) {
        return null
    }

    const minimumDepth = Math.min(...selectedItems.map((item) => item.depth))
    return {
        ...node,
        items: selectedItems.map((item) => ({ ...item, depth: item.depth - minimumDepth })),
    }
}

function getSelectedInlineNodes(nodes: NotebookInlineNode[], element: HTMLElement, range: Range): NotebookInlineNode[] {
    const textLength = getInlineText(nodes).length
    const selectionStart = element.contains(range.startContainer)
        ? getTextOffset(element, range.startContainer, range.startOffset)
        : 0
    const selectionEnd = element.contains(range.endContainer)
        ? getTextOffset(element, range.endContainer, range.endOffset)
        : textLength
    const normalizedStart = Math.max(0, Math.min(selectionStart, textLength))
    const normalizedEnd = Math.max(normalizedStart, Math.min(selectionEnd, textLength))
    const [, selectedAndAfter] = splitInlineNodesAt(nodes, normalizedStart)
    const [selectedChildren] = splitInlineNodesAt(selectedAndAfter, normalizedEnd - normalizedStart)

    return selectedChildren
}

function getInlineLinkPasteResult(
    element: HTMLElement,
    nodeId: string,
    children: NotebookInlineNode[],
    plainText: string
): InlineLinkPasteResult | null {
    const href = sanitizeNotebookLinkHref(plainText)
    if (!href) {
        return null
    }

    const selection = getSelectionRange(element, nodeId)
    if (!selection) {
        return null
    }

    const textLength = getInlineText(children).length
    const selectionStart = Math.max(0, Math.min(Math.min(selection.start, selection.end), textLength))
    const selectionEnd = Math.max(selectionStart, Math.min(Math.max(selection.start, selection.end), textLength))
    if (selectionStart === selectionEnd) {
        return null
    }

    const [beforeSelection, selectionAndAfter] = splitInlineNodesAt(children, selectionStart)
    const [selectedChildren, afterSelection] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)
    if (!getInlineText(selectedChildren)) {
        return null
    }

    return {
        children: normalizeInlineNodes([
            ...beforeSelection,
            ...applyLinkMarkToInlineNodes(selectedChildren, href),
            ...afterSelection,
        ]),
        start: selectionStart,
        end: selectionEnd,
    }
}

function getSelectedLinkHref(nodes: NotebookInlineNode[], range: NotebookTextSelectionRange): string | null {
    const selectedChildren = getInlineNodesInRange(nodes, range)
    const linkedTextNode = selectedChildren.find(
        (node) => node.type === 'text' && (node.marks ?? []).some((mark) => mark.type === 'link')
    )

    if (!linkedTextNode || linkedTextNode.type === 'hardBreak') {
        return null
    }

    return linkedTextNode.marks?.find((mark) => mark.type === 'link')?.href ?? null
}

function getInlineNodesInRange(nodes: NotebookInlineNode[], range: NotebookTextSelectionRange): NotebookInlineNode[] {
    const textLength = getInlineText(nodes).length
    const selectionStart = Math.max(0, Math.min(Math.min(range.start, range.end), textLength))
    const selectionEnd = Math.max(selectionStart, Math.min(Math.max(range.start, range.end), textLength))
    const [, selectionAndAfter] = splitInlineNodesAt(nodes, selectionStart)
    const [selectedChildren] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)

    return selectedChildren
}

function applyLinkMarkToInlineNodes(nodes: NotebookInlineNode[], href: string): NotebookInlineNode[] {
    return nodes.map((node) => {
        if (node.type === 'hardBreak') {
            return node
        }

        const marks: NotebookInlineMark[] = [
            ...(node.marks ?? []).filter((mark) => mark.type !== 'link'),
            { type: 'link', href },
        ]
        return { ...node, marks }
    })
}

function rangeIntersectsNode(range: Range, node: Node): boolean {
    try {
        return range.intersectsNode(node)
    } catch {
        return false
    }
}

function shouldUseMarkdownPaste(plainText: string, html: string, parsedDocument: NotebookDocument): boolean {
    if (!plainText.trim() || !parsedDocument.nodes.length) {
        return false
    }

    if (!html) {
        return true
    }

    if (parsedDocument.nodes.length !== 1) {
        return true
    }

    const [node] = parsedDocument.nodes
    return node.type !== 'paragraph' || hasInlineMarkdownSyntax(plainText)
}

function hasInlineMarkdownSyntax(value: string): boolean {
    return /(\*\*[^*]+\*\*|`[^`]+`|<u>[\s\S]+<\/u>|\[[^\]]+\]\([^)]+\)|(^|[^*])\*[^*\s][^*]*\*)/.test(value)
}

function rekeyNotebookNodes(nodes: NotebookBlockNode[], seed: string): NotebookBlockNode[] {
    return nodes.map((node, index) => ({
        ...cloneNotebookNode(node),
        id: makeEmptyParagraph(`${seed}-${String(index)}`).id,
    }))
}

function isNativeEditableElement(element: HTMLElement): boolean {
    return Boolean(element.closest('input, textarea, select'))
}

function isFormattingToolbarFocused(): boolean {
    return (
        document.activeElement instanceof HTMLElement &&
        Boolean(document.activeElement.closest('.MarkdownNotebook__format-toolbar'))
    )
}

function findTextPosition(root: HTMLElement, offset: number): { node: Node; offset: number } {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    let remaining = offset
    let current = walker.nextNode()

    while (current) {
        const length = current.textContent?.length ?? 0
        if (remaining <= length) {
            return { node: current, offset: remaining }
        }
        remaining -= length
        current = walker.nextNode()
    }

    return { node: root, offset: root.childNodes.length }
}

function toggleInlineMark(
    nodes: NotebookInlineNode[],
    range: NotebookTextSelectionRange,
    markType: NotebookInlineMark['type']
): NotebookInlineNode[] {
    const normalizedStart = Math.min(range.start, range.end)
    const normalizedEnd = Math.max(range.start, range.end)
    let offset = 0
    const output: NotebookInlineNode[] = []

    nodes.forEach((node) => {
        const length = node.type === 'hardBreak' ? 1 : node.text.length
        const nodeStart = offset
        const nodeEnd = offset + length
        offset = nodeEnd

        if (node.type === 'hardBreak' || nodeEnd <= normalizedStart || nodeStart >= normalizedEnd) {
            output.push(node)
            return
        }

        const selectionStart = Math.max(normalizedStart - nodeStart, 0)
        const selectionEnd = Math.min(normalizedEnd - nodeStart, node.text.length)

        if (selectionStart > 0) {
            output.push({ ...node, text: node.text.slice(0, selectionStart) })
        }

        output.push({
            ...node,
            text: node.text.slice(selectionStart, selectionEnd),
            marks: toggleMark(node.marks ?? [], markType),
        })

        if (selectionEnd < node.text.length) {
            output.push({ ...node, text: node.text.slice(selectionEnd) })
        }
    })

    return normalizeInlineNodes(output)
}

function setInlineLinkMark(
    nodes: NotebookInlineNode[],
    range: NotebookTextSelectionRange,
    href: string | null
): NotebookInlineNode[] {
    const normalizedStart = Math.min(range.start, range.end)
    const normalizedEnd = Math.max(range.start, range.end)
    let offset = 0
    const output: NotebookInlineNode[] = []

    nodes.forEach((node) => {
        const length = node.type === 'hardBreak' ? 1 : node.text.length
        const nodeStart = offset
        const nodeEnd = offset + length
        offset = nodeEnd

        if (node.type === 'hardBreak' || nodeEnd <= normalizedStart || nodeStart >= normalizedEnd) {
            output.push(node)
            return
        }

        const selectionStart = Math.max(normalizedStart - nodeStart, 0)
        const selectionEnd = Math.min(normalizedEnd - nodeStart, node.text.length)

        if (selectionStart > 0) {
            output.push({ ...node, text: node.text.slice(0, selectionStart) })
        }

        output.push({
            ...node,
            text: node.text.slice(selectionStart, selectionEnd),
            marks: setLinkMark(node.marks ?? [], href),
        })

        if (selectionEnd < node.text.length) {
            output.push({ ...node, text: node.text.slice(selectionEnd) })
        }
    })

    return normalizeInlineNodes(output)
}

function toggleMark(marks: NotebookInlineMark[], markType: NotebookInlineMark['type']): NotebookInlineMark[] {
    const existing = marks.some((mark) => mark.type === markType)
    if (existing) {
        return marks.filter((mark) => mark.type !== markType)
    }

    if (markType === 'link') {
        return marks
    }

    return [...marks, { type: markType }]
}

function setLinkMark(marks: NotebookInlineMark[], href: string | null): NotebookInlineMark[] | undefined {
    const marksWithoutLink = marks.filter((mark) => mark.type !== 'link')
    const nextMarks = href ? [...marksWithoutLink, { type: 'link' as const, href }] : marksWithoutLink

    return nextMarks.length ? nextMarks : undefined
}

function splitInlineNodesAt(nodes: NotebookInlineNode[], offset: number): [NotebookInlineNode[], NotebookInlineNode[]] {
    const before: NotebookInlineNode[] = []
    const after: NotebookInlineNode[] = []
    let currentOffset = 0

    nodes.forEach((node) => {
        const length = node.type === 'hardBreak' ? 1 : node.text.length
        if (currentOffset + length <= offset) {
            before.push(node)
            currentOffset += length
            return
        }
        if (currentOffset >= offset) {
            after.push(node)
            currentOffset += length
            return
        }
        if (node.type === 'hardBreak') {
            after.push(node)
            currentOffset += length
            return
        }

        const splitOffset = offset - currentOffset
        before.push({ ...node, text: node.text.slice(0, splitOffset) })
        after.push({ ...node, text: node.text.slice(splitOffset) })
        currentOffset += length
    })

    return [normalizeInlineNodes(before), normalizeInlineNodes(after)]
}
