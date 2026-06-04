import './MarkdownNotebook.scss'

import clsx from 'clsx'
import {
    ChangeEvent as ReactChangeEvent,
    ClipboardEvent as ReactClipboardEvent,
    type CSSProperties,
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

import { IconCode, IconDatabase, IconEye, IconGraph, IconList, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { IconBold, IconItalic } from 'lib/lemon-ui/icons'

import { mergeNotebookMarkdownChanges } from './collaboration'
import {
    htmlElementToInlineNodes,
    inlineNodesToHtml,
    makeEmptyParagraph,
    parseMarkdownNotebook,
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
    NotebookTextBlockNode,
    NotebookTextSelectionRange,
} from './types'
import { cloneNotebookNode, getInlineText, getNodeFingerprint, normalizeInlineNodes } from './utils'

export type MarkdownNotebookProps = {
    value: string
    onChange?: (value: string) => void
    mode?: NotebookMode
    registry?: NotebookComponentRegistry
    remoteValue?: string
    clientId?: string
    onConflict?: (conflicts: NotebookCollaborationConflict[]) => void
    initialInsertMenu?: { nodeIndex?: number; query?: string }
    placeholder?: string
    className?: string
    autoFocus?: boolean
    showDebug?: boolean
    'data-attr'?: string
}

type RestoreSelectionRequest = {
    nodeId: string
    start: number
    end: number
    listItemIndex?: number
}

type InsertCommand = {
    key: string
    label: string
    category: string
    description?: string
    icon?: JSX.Element
    run: (targetNodeId: string) => void
}

type InsertMenuState = {
    nodeId: string
    query: string
    selectedIndex: number
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
}

type CrossBlockSelectionDragState = {
    anchorRange: Range
    originX: number
    originY: number
    isDragging: boolean
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

type NotebookComponentShellProps = {
    node: NotebookComponentBlockNode
    mode: NotebookMode
    componentPanels: ComponentPanelVisibility
    registry: NotebookComponentRegistry
    toggleComponentPanel: (panel: ComponentPanel) => void
    setBlockRef: (element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    deleteNode: () => void
    insertParagraphAfterNode: () => void
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
const INSERT_MENU_PLACEHOLDER = 'Search for tool'
const INSERT_MENU_WIDTH = 384
const INSERT_MENU_VIEWPORT_PADDING = 12
const NOTEBOOK_SELECTABLE_BLOCK_SELECTOR =
    '.MarkdownNotebook__text-block, .MarkdownNotebook__list-item-content, .MarkdownNotebook__component-shell, .MarkdownNotebook__list-block, .MarkdownNotebook__code-block'

export function MarkdownNotebook({
    value,
    onChange,
    mode = 'edit',
    registry,
    remoteValue,
    onConflict,
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
    const [componentPanels, setComponentPanels] = useState<Record<string, ComponentPanelVisibility>>({})
    const [isDebugOpen, setIsDebugOpen] = useState(false)
    const [debugMarkdown, setDebugMarkdown] = useState(value)
    const debugDrawerId = useId()
    const notebookRef = useRef<HTMLDivElement | null>(null)
    const documentRef = useRef(document)
    const blockRefs = useRef<Record<string, HTMLElement | null>>({})
    const listItemRefs = useRef<Record<string, HTMLElement | null>>({})
    const crossBlockSelectionRef = useRef<CrossBlockSelectionDragState | null>(null)
    const focusNodeRef = useRef<string | null>(null)
    const restoreSelectionRef = useRef<RestoreSelectionRequest | null>(null)
    const lastSerializedValueRef = useRef(value)
    const lastBaseValueRef = useRef(value)
    const lastRemoteValueRef = useRef(remoteValue)
    const initialInsertMenuAppliedRef = useRef(false)
    const emptyNodeRef = useRef<NotebookTextBlockNode>(makeEmptyParagraph('initial-empty'))

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
        lastSerializedValueRef.current = value
        lastBaseValueRef.current = value
    }, [value])

    useEffect(() => {
        if (!remoteValue || remoteValue === lastRemoteValueRef.current) {
            return
        }

        const mergeResult = mergeNotebookMarkdownChanges({
            baseMarkdown: lastBaseValueRef.current,
            localMarkdown: lastSerializedValueRef.current,
            remoteMarkdown: remoteValue,
        })
        lastRemoteValueRef.current = remoteValue
        lastBaseValueRef.current = mergeResult.mergedMarkdown
        commitDocument(mergeResult.document)

        if (mergeResult.conflicts.length) {
            onConflict?.(mergeResult.conflicts)
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [remoteValue, onConflict])

    useLayoutEffect(() => {
        const request = restoreSelectionRef.current
        if (request) {
            restoreSelectionRef.current = null
            const element =
                request.listItemIndex === undefined
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
            setInsertMenu({ nodeId: node.id, query: initialInsertMenu.query ?? '', selectedIndex: 0 })
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [initialInsertMenu, mode])

    const commitDocument = useCallback(
        (nextDocument: NotebookDocument): void => {
            const editableDocument = ensureEditableTrailingParagraph(nextDocument)
            const serialized = serializeMarkdownNotebook(editableDocument)
            documentRef.current = editableDocument
            lastSerializedValueRef.current = serialized
            setDebugMarkdown(serialized)
            setDocument(editableDocument)
            onChange?.(serialized)
        },
        [onChange]
    )

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

    const deleteNodeBefore = useCallback(
        (nodeId: string): boolean => {
            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const nodeIndex = nodes.findIndex((node) => node.id === nodeId)
            if (nodeIndex <= 0) {
                return false
            }

            commitDocument({
                ...currentDocument,
                nodes: nodes.filter((_, index) => index !== nodeIndex - 1),
            })
            restoreSelectionRef.current = { nodeId, start: 0, end: 0 }
            return true
        },
        [commitDocument]
    )

    const renderedNodes = getRenderedNodes()
    const showInsertBoundaries = mode === 'edit' && document.nodes.length > 0
    const placeholderNodeId = hasNotebookContent(renderedNodes) ? null : renderedNodes[0]?.id
    const insertCommands = useMemo(
        () => buildInsertCommands(mergedRegistry, replaceNodeWithInsertedComponent),
        [mergedRegistry, replaceNodeWithInsertedComponent]
    )

    function getRenderedNodes(): NotebookBlockNode[] {
        if (document.nodes.length || mode === 'view') {
            return document.nodes
        }
        return [emptyNodeRef.current]
    }

    const updateFloatingToolbarFromSelection = useCallback((): void => {
        if (mode !== 'edit') {
            setFloatingToolbar(null)
            return
        }

        const selection = window.getSelection()
        if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
            setFloatingToolbar(null)
            return
        }

        const domRange = selection.getRangeAt(0)
        const selectedEntry = Object.entries(blockRefs.current).find(([, element]) =>
            element?.contains(domRange.commonAncestorContainer)
        )
        if (!selectedEntry) {
            setFloatingToolbar(null)
            return
        }

        const [nodeId, element] = selectedEntry
        if (!element) {
            setFloatingToolbar(null)
            return
        }

        const range = getSelectionRange(element, nodeId)
        if (!range || range.start === range.end) {
            setFloatingToolbar(null)
            return
        }

        const selectedNode = documentRef.current.nodes.find(
            (node): node is NotebookTextBlockNode => node.id === nodeId && isTextBlockNode(node)
        )
        const selectionRect = getSelectionClientRect(domRange)
        if (!selectedNode || !selectionRect) {
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

    useEffect(() => {
        if (mode !== 'edit') {
            setFloatingToolbar(null)
            crossBlockSelectionRef.current = null
            return
        }

        const handleDocumentSelectionChange = (): void => updateFloatingToolbarFromSelection()

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

            if (!dragState.isDragging) {
                const distance = Math.hypot(event.clientX - dragState.originX, event.clientY - dragState.originY)
                if (distance < CROSS_BLOCK_SELECTION_DRAG_THRESHOLD) {
                    return
                }
                dragState.isDragging = true
            }

            const focusRange = getNotebookBlockCaretRangeFromPoint(event.clientX, event.clientY, notebookElement)
            if (!focusRange) {
                return
            }

            event.preventDefault()
            selectBetweenRanges(dragState.anchorRange, focusRange)
            setFloatingToolbar(null)
        }

        const handleMouseUp = (): void => {
            const dragState = crossBlockSelectionRef.current
            crossBlockSelectionRef.current = null
            if (dragState?.isDragging) {
                updateFloatingToolbarFromSelection()
            }
        }

        window.document.addEventListener('mousemove', handleMouseMove)
        window.document.addEventListener('mouseup', handleMouseUp)

        return () => {
            window.document.removeEventListener('mousemove', handleMouseMove)
            window.document.removeEventListener('mouseup', handleMouseUp)
        }
    }, [mode, updateFloatingToolbarFromSelection])

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
            originX: event.clientX,
            originY: event.clientY,
            isDragging: false,
        }
    }

    const handleCopy = (event: ReactClipboardEvent<HTMLDivElement>): void => {
        if (event.target instanceof HTMLElement && isNativeEditableElement(event.target)) {
            return
        }

        const notebookElement = notebookRef.current
        const markdown = notebookElement
            ? getSelectedNotebookMarkdown(
                  window.getSelection(),
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
        event.clipboardData.setData('text/plain', markdown)
        event.clipboardData.setData('text/markdown', markdown)
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

        updateNode(activeSelectionRange.nodeId, (node) => {
            if (!isTextBlockNode(node)) {
                return node
            }
            return {
                ...node,
                children: toggleInlineMark(node.children, activeSelectionRange, markType),
            }
        })
        restoreSelectionRef.current = activeSelectionRange
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
        setInsertMenu({ nodeId, query, selectedIndex: 0 })
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

                targetIndex += step
            }

            return false
        },
        []
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

    return (
        <div
            className={clsx('MarkdownNotebook', isDebugOpen && 'MarkdownNotebook--debug-open', className)}
            data-attr={dataAttr}
            ref={notebookRef}
            onCopy={handleCopy}
        >
            <div className="MarkdownNotebook__debug-layout">
                <div className="MarkdownNotebook__main">
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
                    <div className="MarkdownNotebook__canvas" onMouseLeave={() => setActiveRowIndex(null)}>
                        {showInsertBoundaries ? (
                            <InsertBoundaryButton
                                boundaryIndex={0}
                                isAvailable={isInsertBoundaryAvailable(renderedNodes, 0, insertMenu?.nodeId)}
                                isVisible={isInsertBoundaryVisible(
                                    renderedNodes,
                                    0,
                                    activeRowIndex,
                                    insertMenu?.nodeId
                                )}
                                insertEmptyParagraphAtBoundary={insertEmptyParagraphAtBoundary}
                                setActiveRowIndex={(boundaryIndex) =>
                                    setActiveRowIndex(getBoundaryActiveRowIndex(renderedNodes, boundaryIndex))
                                }
                            />
                        ) : null}
                        {renderedNodes.map((node, index) => {
                            const isInsertMenuOpen = insertMenu?.nodeId === node.id
                            const shouldShowInlineInsertMenuButton =
                                isBlankInsertMenuButtonRow(node) || (isInsertMenuOpen && isTextBlockNode(node))
                            const hasInvalidInsertMenuQuery =
                                isInsertMenuOpen &&
                                insertMenu.query.length > 0 &&
                                getFilteredInsertCommands(insertCommands, insertMenu.query).length === 0
                            const submitInsertMenuSelection = (queryOverride?: string): boolean => {
                                if (!isInsertMenuOpen) {
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

                            return (
                                <Fragment key={node.id}>
                                    <div
                                        className={clsx(
                                            'MarkdownNotebook__row',
                                            isInsertMenuOpen && 'MarkdownNotebook__row--insert-menu-open'
                                        )}
                                        onMouseEnter={() => setActiveRowIndex(index)}
                                        onFocusCapture={() => setActiveRowIndex(index)}
                                    >
                                        {renderNode({
                                            node,
                                            mode,
                                            placeholder: isInsertMenuOpen
                                                ? INSERT_MENU_PLACEHOLDER
                                                : node.id === placeholderNodeId
                                                  ? placeholder
                                                  : undefined,
                                            registry: mergedRegistry,
                                            componentPanels:
                                                componentPanels[node.id] ?? DEFAULT_COMPONENT_PANEL_VISIBILITY,
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
                                            setListItemRef: (itemIndex, element) => {
                                                listItemRefs.current[getListItemRefKey(node.id, itemIndex)] = element
                                            },
                                            updateNode,
                                            replaceNodeWithNodes,
                                            deleteNode: () => updateNode(node.id, () => null),
                                            insertParagraphAfterNode: () => insertEmptyParagraphAfterNode(node.id),
                                            deleteNodeBefore,
                                            moveFocusToAdjacentNode,
                                            moveFocusToAdjacentListItem,
                                            openInsertMenu: (query = '') => openInsertMenu(node.id, query),
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
                                                if (isInsertMenuOpen) {
                                                    setInsertMenu(null)
                                                    return
                                                }
                                                openInsertMenu(node.id, getInlineInsertMenuQuery(node))
                                            },
                                            showInlineInsertMenuButton:
                                                mode === 'edit' && shouldShowInlineInsertMenuButton,
                                            isInlineInsertMenuButtonVisible:
                                                activeRowIndex === index || isInsertMenuOpen,
                                            isInsertMenuOpen,
                                            hasInvalidInsertMenuQuery,
                                            submitInsertMenuSelection,
                                            handleSelectionChange,
                                            startCrossBlockSelection,
                                            restoreSelectionRef,
                                        })}
                                        {isInsertMenuOpen ? (
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
                                                activeRowIndex,
                                                insertMenu?.nodeId
                                            )}
                                            insertEmptyParagraphAtBoundary={insertEmptyParagraphAtBoundary}
                                            setActiveRowIndex={(boundaryIndex) =>
                                                setActiveRowIndex(
                                                    getBoundaryActiveRowIndex(renderedNodes, boundaryIndex)
                                                )
                                            }
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
    toggleComponentPanel,
    setBlockRef,
    setListItemRef,
    updateNode,
    replaceNodeWithNodes,
    deleteNode,
    insertParagraphAfterNode,
    deleteNodeBefore,
    moveFocusToAdjacentNode,
    moveFocusToAdjacentListItem,
    openInsertMenu,
    closeInsertMenu,
    moveInsertMenuSelection,
    toggleInsertMenu,
    showInlineInsertMenuButton,
    isInlineInsertMenuButtonVisible,
    isInsertMenuOpen,
    hasInvalidInsertMenuQuery,
    submitInsertMenuSelection,
    handleSelectionChange,
    startCrossBlockSelection,
    restoreSelectionRef,
}: {
    node: NotebookBlockNode
    mode: NotebookMode
    placeholder: string | undefined
    registry: NotebookComponentRegistry
    componentPanels: ComponentPanelVisibility
    toggleComponentPanel: (panel: ComponentPanel) => void
    setBlockRef: (element: HTMLElement | null) => void
    setListItemRef: (itemIndex: number, element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    replaceNodeWithNodes: (nodeId: string, replacementNodes: NotebookBlockNode[]) => void
    deleteNode: () => void
    insertParagraphAfterNode: () => void
    deleteNodeBefore: (nodeId: string) => boolean
    moveFocusToAdjacentNode: (nodeId: string, direction: InsertMenuSelectionDirection, offset: number) => boolean
    moveFocusToAdjacentListItem: (
        nodeId: string,
        itemIndex: number,
        direction: InsertMenuSelectionDirection,
        offset: number
    ) => boolean
    openInsertMenu: (query?: string) => void
    closeInsertMenu: () => void
    moveInsertMenuSelection: (direction: InsertMenuSelectionDirection) => void
    toggleInsertMenu: () => void
    showInlineInsertMenuButton: boolean
    isInlineInsertMenuButtonVisible: boolean
    isInsertMenuOpen: boolean
    hasInvalidInsertMenuQuery: boolean
    submitInsertMenuSelection: (queryOverride?: string) => boolean
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
                registry={registry}
                toggleComponentPanel={toggleComponentPanel}
                setBlockRef={setBlockRef}
                updateNode={updateNode}
                deleteNode={deleteNode}
                insertParagraphAfterNode={insertParagraphAfterNode}
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
            updateNode={updateNode}
            replaceNodeWithNodes={replaceNodeWithNodes}
            deleteNodeBefore={deleteNodeBefore}
            moveFocusToAdjacentNode={moveFocusToAdjacentNode}
            openInsertMenu={openInsertMenu}
            closeInsertMenu={closeInsertMenu}
            moveInsertMenuSelection={moveInsertMenuSelection}
            toggleInsertMenu={toggleInsertMenu}
            showInlineInsertMenuButton={showInlineInsertMenuButton}
            isInlineInsertMenuButtonVisible={isInlineInsertMenuButtonVisible}
            isInsertMenuOpen={isInsertMenuOpen}
            hasInvalidInsertMenuQuery={hasInvalidInsertMenuQuery}
            submitInsertMenuSelection={submitInsertMenuSelection}
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

function EditableTextBlock({
    node,
    mode,
    placeholder,
    setBlockRef,
    updateNode,
    replaceNodeWithNodes,
    deleteNodeBefore,
    moveFocusToAdjacentNode,
    openInsertMenu,
    closeInsertMenu,
    moveInsertMenuSelection,
    toggleInsertMenu,
    showInlineInsertMenuButton,
    isInlineInsertMenuButtonVisible,
    isInsertMenuOpen,
    hasInvalidInsertMenuQuery,
    submitInsertMenuSelection,
    handleSelectionChange,
    startCrossBlockSelection,
    restoreSelectionRef,
}: {
    node: NotebookTextBlockNode
    mode: NotebookMode
    placeholder: string | undefined
    setBlockRef: (element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    replaceNodeWithNodes: (nodeId: string, replacementNodes: NotebookBlockNode[]) => void
    deleteNodeBefore: (nodeId: string) => boolean
    moveFocusToAdjacentNode: (nodeId: string, direction: InsertMenuSelectionDirection, offset: number) => boolean
    openInsertMenu: (query?: string) => void
    closeInsertMenu: () => void
    moveInsertMenuSelection: (direction: InsertMenuSelectionDirection) => void
    toggleInsertMenu: () => void
    showInlineInsertMenuButton: boolean
    isInlineInsertMenuButtonVisible: boolean
    isInsertMenuOpen: boolean
    hasInvalidInsertMenuQuery: boolean
    submitInsertMenuSelection: (queryOverride?: string) => boolean
    handleSelectionChange: () => void
    startCrossBlockSelection: (event: ReactMouseEvent<HTMLElement>) => void
    restoreSelectionRef: MutableRefObject<RestoreSelectionRequest | null>
}): JSX.Element {
    const elementRef = useRef<HTMLElement | null>(null)
    const skipDomSyncForHtmlRef = useRef<string | null>(null)
    const renderedHtml = useMemo(() => inlineNodesToHtml(node.children), [node.children])
    const text = getInlineText(node.children)
    const isEmpty = text.length === 0
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
        const slashQuery = getSlashCommandQuery(elementText)
        if (slashQuery !== null) {
            if (isInsertMenuOpen) {
                updateElementAndChildren(element, [])
                closeInsertMenu()
                return
            }

            const queryChildren: NotebookInlineNode[] = slashQuery ? [{ type: 'text', text: slashQuery }] : []
            updateElementAndChildren(element, queryChildren)
            openInsertMenu(slashQuery)
            return
        }

        const nextChildren = updateChildren(elementChildren)
        const nextText = getInlineText(nextChildren)
        if (isInsertMenuOpen) {
            openInsertMenu(nextText)
            return
        }

        closeInsertMenu()
    }

    const handlePaste = (event: ReactClipboardEvent<HTMLElement>): void => {
        const plainText = event.clipboardData.getData('text/plain')
        const html = event.clipboardData.getData('text/html')
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
        if (isInsertMenuOpen && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
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
            const insertMenuQuery = slashQuery ?? (isInsertMenuOpen ? inputText : undefined)

            if (submitInsertMenuSelection(insertMenuQuery)) {
                event.preventDefault()
                return
            }

            event.preventDefault()
            const selection = getCollapsedSelectionRange(event.currentTarget, node.id)
            const offset = selection?.start ?? getInlineText(node.children).length
            const [before, after] = splitInlineNodesAt(node.children, offset)
            const nextParagraph = makeEmptyParagraph(`after-${node.id}`)
            nextParagraph.children = after

            replaceNodeWithNodes(node.id, [{ ...node, children: before }, nextParagraph])
            restoreSelectionRef.current = { nodeId: nextParagraph.id, start: 0, end: 0 }
            return
        }

        if (event.key === 'Backspace') {
            const selection = getCollapsedSelectionRange(event.currentTarget, node.id)
            if (selection?.start === 0 && selection.end === 0 && deleteNodeBefore(node.id)) {
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
                <LemonButton
                    size="xsmall"
                    icon={<span className="MarkdownNotebook__line-insert-menu-icon">/</span>}
                    className="MarkdownNotebook__line-insert-menu-button"
                    tooltip="Add block"
                    onClick={handleInsertMenuButtonClick}
                    aria-label={isInsertMenuOpen ? 'Close add block menu' : 'Open add block menu'}
                    aria-expanded={isInsertMenuOpen}
                    tabIndex={isInlineInsertMenuButtonVisible ? 0 : -1}
                />
            ) : null}
            <TextTag
                ref={setElementRef}
                className={clsx(
                    'MarkdownNotebook__text-block',
                    `MarkdownNotebook__text-block--${node.type}`,
                    hasInvalidInsertMenuQuery && 'MarkdownNotebook__text-block--invalid-insert-filter'
                )}
                contentEditable={mode === 'edit'}
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
    setActiveRowIndex,
}: {
    boundaryIndex: number
    isAvailable: boolean
    isVisible: boolean
    insertEmptyParagraphAtBoundary: (boundaryIndex: number) => void
    setActiveRowIndex: (boundaryIndex: number) => void
}): JSX.Element {
    return (
        <div className="MarkdownNotebook__insert-boundary" onMouseEnter={() => setActiveRowIndex(boundaryIndex)}>
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
    setBlockStyle,
}: {
    node: NotebookBlockNode
    placement: 'above' | 'below'
    top: number
    left: number
    applyInlineMark: (markType: NotebookInlineMark['type']) => void
    setBlockStyle: (nodeId: string, style: 'paragraph' | 'blockquote' | 1 | 2 | 3) => void
}): JSX.Element {
    const toolbarStyle = {
        '--markdown-notebook-format-toolbar-top': `${top}px`,
        '--markdown-notebook-format-toolbar-left': `${left}px`,
    } as CSSProperties

    return (
        <div
            className={clsx('MarkdownNotebook__format-toolbar', `MarkdownNotebook__format-toolbar--${placement}`)}
            style={toolbarStyle}
            onMouseDown={(event) => event.preventDefault()}
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
        </div>
    )
}

function NotebookComponentShell({
    node,
    mode,
    componentPanels,
    registry,
    toggleComponentPanel,
    setBlockRef,
    updateNode,
    deleteNode,
    insertParagraphAfterNode,
}: NotebookComponentShellProps): JSX.Element {
    const definition = getMarkdownNotebookComponentDefinition(registry, node.tagName)
    const errors = [...(node.errors ?? []), ...(definition?.validateProps?.(node.props) ?? [])]
    const ViewComponent = definition?.ViewComponent
    const EditComponent = definition?.EditComponent ?? definition?.ViewComponent
    const showViewPanel = mode === 'view' || componentPanels.view
    const showEditPanel = mode === 'edit' && componentPanels.edit
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

        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            insertParagraphAfterNode()
        }
    }

    return (
        <div
            className={clsx(
                'MarkdownNotebook__component-shell',
                errors.length && 'MarkdownNotebook__component-shell--error'
            )}
            ref={setBlockRef}
            tabIndex={mode === 'edit' ? 0 : undefined}
            onKeyDown={handleKeyDown}
        >
            <div className="MarkdownNotebook__component-toolbar">
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
                    <div className="MarkdownNotebook__component-actions">
                        <LemonButton
                            size="xsmall"
                            icon={<IconPencil />}
                            active={componentPanels.edit}
                            tooltip="Edit mode"
                            onClick={() => toggleComponentPanel('edit')}
                        />
                        <LemonButton
                            size="xsmall"
                            icon={<IconEye />}
                            active={componentPanels.view}
                            tooltip="View mode"
                            onClick={() => toggleComponentPanel('view')}
                        />
                        <LemonButton
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
        previousDefinition === nextDefinition &&
        previousProps.node.id === nextProps.node.id &&
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
                                    onClose()
                                }}
                            >
                                {command.icon ? (
                                    <span className="MarkdownNotebook__insert-item-icon">{command.icon}</span>
                                ) : null}
                                <span>{command.label}</span>
                            </button>
                        ))}
                    </div>
                </div>
            ))}
            {!filteredCommands.length ? <div className="MarkdownNotebook__empty-menu">No components found</div> : null}
        </div>
    )
}

function getFilteredInsertCommands(commands: InsertCommand[], query: string): InsertCommand[] {
    const normalizedQuery = query.trim().toLowerCase()
    if (!normalizedQuery) {
        return commands
    }

    return commands.filter((command) =>
        `${command.label} ${command.category} ${command.description ?? ''}`.toLowerCase().includes(normalizedQuery)
    )
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
    replaceNodeWithInsertedComponent: (nodeId: string, nextNode: NotebookComponentBlockNode) => void
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
            run: (targetNodeId) =>
                insertComponent(targetNodeId, 'Query', {
                    query: {
                        kind: 'DataTableNode',
                        source: { kind: 'EventsQuery', select: ['*', 'event', 'person', 'timestamp'] },
                    },
                }),
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

    return [...queryCommands, ...dataCommands, ...experimentCommands, ...mediaCommands]
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

function getSlashCommandQuery(text: string): string | null {
    const trimmedText = text.trimStart()
    return trimmedText.startsWith('/') ? trimmedText.slice(1) : null
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
    activeRowIndex: number | null,
    insertMenuNodeId?: string
): boolean {
    if (activeRowIndex === null || !isInsertBoundaryAvailable(nodes, boundaryIndex, insertMenuNodeId)) {
        return false
    }

    return boundaryIndex === activeRowIndex || boundaryIndex === activeRowIndex + 1
}

function getBoundaryActiveRowIndex(nodes: NotebookBlockNode[], boundaryIndex: number): number | null {
    const previousRowIndex = boundaryIndex - 1
    const nextRowIndex = boundaryIndex

    if (previousRowIndex >= 0 && !isInlineInsertMenuRow(nodes[previousRowIndex])) {
        return previousRowIndex
    }
    if (nextRowIndex < nodes.length && !isInlineInsertMenuRow(nodes[nextRowIndex])) {
        return nextRowIndex
    }
    return null
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
    if (!element.contains(range.commonAncestorContainer)) {
        return null
    }

    return {
        nodeId,
        start: getTextOffset(element, range.startContainer, range.startOffset),
        end: getTextOffset(element, range.endContainer, range.endOffset),
    }
}

function getSelectionClientRect(range: Range): DOMRect | null {
    const rect = range.getBoundingClientRect()
    if (rect.width || rect.height) {
        return rect
    }

    return range.getClientRects()[0] ?? null
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
        const editableTextElement = element?.closest(
            '.MarkdownNotebook__text-block, .MarkdownNotebook__list-item-content'
        )
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

        selectedNodes.push(node)
    })

    if (!selectedNodes.length) {
        return null
    }

    return serializeMarkdownNotebook({ type: 'doc', nodes: selectedNodes, errors: [] })
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
