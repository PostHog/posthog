import './MarkdownNotebook.scss'

import clsx from 'clsx'
import {
    ClipboardEvent as ReactClipboardEvent,
    type CSSProperties,
    FormEvent,
    Key,
    KeyboardEvent,
    MutableRefObject,
    ReactNode,
    useCallback,
    useEffect,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from 'react'

import { IconDatabase, IconEye, IconGraph, IconList, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { IconBold, IconItalic } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'

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
    NotebookComponentProps,
    NotebookComponentRegistry,
    NotebookDocument,
    NotebookInlineMark,
    NotebookInlineNode,
    NotebookMode,
    NotebookTextBlockNode,
    NotebookTextSelectionRange,
} from './types'
import { cloneNotebookNode, getInlineText, normalizeInlineNodes } from './utils'

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
    'data-attr'?: string
}

type RestoreSelectionRequest = {
    nodeId: string
    start: number
    end: number
}

type InsertCommand = {
    key: string
    label: string
    category: string
    description?: string
    icon?: JSX.Element
    run: (targetNodeId: string) => void
}

type FloatingToolbarState = {
    range: NotebookTextSelectionRange
    node: NotebookTextBlockNode
    top: number
    left: number
}

type ComponentPanel = 'view' | 'edit'

type ComponentPanelVisibility = Record<ComponentPanel, boolean>

const DEFAULT_COMPONENT_PANEL_VISIBILITY: ComponentPanelVisibility = {
    view: true,
    edit: false,
}

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
    'data-attr': dataAttr = 'markdown-notebook',
}: MarkdownNotebookProps): JSX.Element {
    const mergedRegistry = useMemo(
        () => mergeMarkdownNotebookRegistries(getMarkdownNotebookDefaultRegistry(), registry),
        [registry]
    )
    const [document, setDocument] = useState<NotebookDocument>(() => parseMarkdownNotebook(value))
    const [floatingToolbar, setFloatingToolbar] = useState<FloatingToolbarState | null>(null)
    const [insertMenu, setInsertMenu] = useState<{ nodeId: string; query: string } | null>(null)
    const [componentPanels, setComponentPanels] = useState<Record<string, ComponentPanelVisibility>>({})
    const documentRef = useRef(document)
    const blockRefs = useRef<Record<string, HTMLElement | null>>({})
    const restoreSelectionRef = useRef<RestoreSelectionRequest | null>(null)
    const lastSerializedValueRef = useRef(value)
    const lastBaseValueRef = useRef(value)
    const lastRemoteValueRef = useRef(remoteValue)
    const initialInsertMenuAppliedRef = useRef(false)
    const emptyNodeRef = useRef<NotebookTextBlockNode>(makeEmptyParagraph('initial-empty'))

    useEffect(() => {
        if (value === lastSerializedValueRef.current) {
            return
        }

        setDocument((currentDocument) => {
            const nextDocument = parseMarkdownNotebook(value)
            const reconciledDocument = reconcileNotebookDocuments(currentDocument, nextDocument).document
            documentRef.current = reconciledDocument
            return reconciledDocument
        })
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
        if (!request) {
            return
        }

        restoreSelectionRef.current = null
        const element = blockRefs.current[request.nodeId]
        if (element) {
            restoreSelection(element, request.start, request.end)
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
            setInsertMenu({ nodeId: node.id, query: initialInsertMenu.query ?? '' })
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [initialInsertMenu, mode])

    const commitDocument = useCallback(
        (nextDocument: NotebookDocument): void => {
            const serialized = serializeMarkdownNotebook(nextDocument)
            documentRef.current = nextDocument
            lastSerializedValueRef.current = serialized
            setDocument(nextDocument)
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

    const insertNodeAfter = useCallback(
        (nodeId: string, nextNode: NotebookBlockNode): void => {
            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const insertionIndex = nodes.findIndex((node) => node.id === nodeId)
            const nextNodes =
                insertionIndex === -1
                    ? [...nodes, nextNode]
                    : [...nodes.slice(0, insertionIndex + 1), nextNode, ...nodes.slice(insertionIndex + 1)]

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

    const renderedNodes = getRenderedNodes()
    const insertCommands = useMemo(
        () => buildInsertCommands(mergedRegistry, replaceNode, insertNodeAfter, updateNode),
        [insertNodeAfter, mergedRegistry, replaceNode, updateNode]
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

        setFloatingToolbar({
            range,
            node: selectedNode,
            top: Math.max(48, Math.round(selectionRect.top)),
            left: Math.min(
                window.innerWidth - 16,
                Math.max(16, Math.round(selectionRect.left + selectionRect.width / 2))
            ),
        })
    }, [mode])

    useEffect(() => {
        if (mode !== 'edit') {
            setFloatingToolbar(null)
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

    return (
        <div className={clsx('MarkdownNotebook', className)} data-attr={dataAttr}>
            {document.errors.length ? (
                <div className="MarkdownNotebook__parse-errors">
                    {document.errors.map((error) => (
                        <div key={`${error.line}:${error.message}`}>{error.message}</div>
                    ))}
                </div>
            ) : null}
            <div className="MarkdownNotebook__canvas">
                {renderedNodes.map((node) => (
                    <div className="MarkdownNotebook__row" key={node.id}>
                        {renderNode({
                            node,
                            mode,
                            placeholder,
                            registry: mergedRegistry,
                            componentPanels: componentPanels[node.id] ?? DEFAULT_COMPONENT_PANEL_VISIBILITY,
                            toggleComponentPanel: (panel) =>
                                setComponentPanels((current) => {
                                    const currentPanels = current[node.id] ?? DEFAULT_COMPONENT_PANEL_VISIBILITY
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
                            updateNode,
                            replaceNodeWithNodes,
                            deleteNode: () => updateNode(node.id, () => null),
                            openInsertMenu: (query = '') => setInsertMenu({ nodeId: node.id, query }),
                            closeInsertMenu: () => setInsertMenu(null),
                            handleSelectionChange,
                            restoreSelectionRef,
                        })}
                        {insertMenu?.nodeId === node.id ? (
                            <InsertMenu
                                query={insertMenu.query}
                                commands={insertCommands}
                                targetNodeId={node.id}
                                onClose={() => setInsertMenu(null)}
                            />
                        ) : null}
                    </div>
                ))}
            </div>
            {floatingToolbar && mode === 'edit' ? (
                <FormattingToolbar
                    node={floatingToolbar.node}
                    top={floatingToolbar.top}
                    left={floatingToolbar.left}
                    applyInlineMark={applyInlineMark}
                    setBlockStyle={setBlockStyle}
                />
            ) : null}
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
    updateNode,
    replaceNodeWithNodes,
    deleteNode,
    openInsertMenu,
    closeInsertMenu,
    handleSelectionChange,
    restoreSelectionRef,
}: {
    node: NotebookBlockNode
    mode: NotebookMode
    placeholder: string
    registry: NotebookComponentRegistry
    componentPanels: ComponentPanelVisibility
    toggleComponentPanel: (panel: ComponentPanel) => void
    setBlockRef: (element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    replaceNodeWithNodes: (nodeId: string, replacementNodes: NotebookBlockNode[]) => void
    deleteNode: () => void
    openInsertMenu: (query?: string) => void
    closeInsertMenu: () => void
    handleSelectionChange: () => void
    restoreSelectionRef: MutableRefObject<RestoreSelectionRequest | null>
}): JSX.Element {
    if (node.type === 'component') {
        return (
            <NotebookComponentShell
                node={node}
                mode={mode}
                componentPanels={componentPanels}
                registry={registry}
                toggleComponentPanel={toggleComponentPanel}
                updateNode={updateNode}
                deleteNode={deleteNode}
            />
        )
    }

    if (node.type === 'list') {
        const ListTag = node.ordered ? 'ol' : 'ul'
        return (
            <div className="MarkdownNotebook__list-block">
                <ListTag>
                    {node.items.map((item, index) => (
                        <li key={index}>{renderInlineNodes(item)}</li>
                    ))}
                </ListTag>
                {mode === 'edit' ? <RowInsertButton openInsertMenu={openInsertMenu} /> : null}
            </div>
        )
    }

    if (node.type === 'code') {
        return (
            <pre className="MarkdownNotebook__code-block">
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
            openInsertMenu={openInsertMenu}
            closeInsertMenu={closeInsertMenu}
            handleSelectionChange={handleSelectionChange}
            restoreSelectionRef={restoreSelectionRef}
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
    openInsertMenu,
    closeInsertMenu,
    handleSelectionChange,
    restoreSelectionRef,
}: {
    node: NotebookTextBlockNode
    mode: NotebookMode
    placeholder: string
    setBlockRef: (element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    replaceNodeWithNodes: (nodeId: string, replacementNodes: NotebookBlockNode[]) => void
    openInsertMenu: (query?: string) => void
    closeInsertMenu: () => void
    handleSelectionChange: () => void
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
    }, [renderedHtml])

    const updateFromElement = (element: HTMLElement): NotebookInlineNode[] => {
        const nextChildren = htmlElementToInlineNodes(element)
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

    const handleInput = (event: FormEvent<HTMLElement>): void => {
        const element = event.currentTarget
        const nextChildren = updateFromElement(element)
        const nextText = getInlineText(nextChildren)
        if (nextText.startsWith('/')) {
            openInsertMenu(nextText.slice(1))
        } else {
            closeInsertMenu()
        }
    }

    const handlePaste = (event: ReactClipboardEvent<HTMLElement>): void => {
        const html = event.clipboardData.getData('text/html')
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
        if (event.key === 'Enter' && !event.shiftKey) {
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

        if (event.key === 'Backspace' && isEmpty) {
            event.preventDefault()
            updateNode(node.id, () => null)
        }
    }

    return (
        <div className="MarkdownNotebook__text-row">
            {mode === 'edit' && isEmpty ? <RowInsertButton openInsertMenu={openInsertMenu} /> : null}
            <TextTag
                ref={setElementRef}
                className={clsx('MarkdownNotebook__text-block', `MarkdownNotebook__text-block--${node.type}`)}
                contentEditable={mode === 'edit'}
                suppressContentEditableWarning
                data-placeholder={isEmpty ? placeholder : undefined}
                onInput={handleInput}
                onPaste={handlePaste}
                onBlur={handleBlur}
                onKeyDown={handleKeyDown}
                onMouseUp={handleSelectionChange}
                onKeyUp={handleSelectionChange}
            />
        </div>
    )
}

function RowInsertButton({ openInsertMenu }: { openInsertMenu: (query?: string) => void }): JSX.Element {
    return (
        <LemonButton
            size="xsmall"
            icon={<IconPlus />}
            className="MarkdownNotebook__row-plus"
            tooltip="Add component"
            onClick={() => openInsertMenu('')}
            aria-label="Add component"
        />
    )
}

function FormattingToolbar({
    node,
    top,
    left,
    applyInlineMark,
    setBlockStyle,
}: {
    node: NotebookBlockNode
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
            className="MarkdownNotebook__format-toolbar"
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
    updateNode,
    deleteNode,
}: {
    node: NotebookComponentBlockNode
    mode: NotebookMode
    componentPanels: ComponentPanelVisibility
    registry: NotebookComponentRegistry
    toggleComponentPanel: (panel: ComponentPanel) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    deleteNode: () => void
}): JSX.Element {
    const definition = getMarkdownNotebookComponentDefinition(registry, node.tagName)
    const errors = [...(node.errors ?? []), ...(definition?.validateProps?.(node.props) ?? [])]
    const ViewComponent = definition?.ViewComponent
    const EditComponent = definition?.EditComponent ?? definition?.ViewComponent
    const showViewPanel = mode === 'view' || componentPanels.view
    const showEditPanel = mode === 'edit' && componentPanels.edit
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

    return (
        <div
            className={clsx(
                'MarkdownNotebook__component-shell',
                errors.length && 'MarkdownNotebook__component-shell--error'
            )}
        >
            <div className="MarkdownNotebook__component-toolbar">
                <div className="MarkdownNotebook__component-title">
                    {definition?.icon}
                    <span>{definition?.label ?? node.tagName}</span>
                </div>
                {mode === 'edit' ? (
                    <div className="MarkdownNotebook__component-actions">
                        <LemonButton
                            size="xsmall"
                            icon={<IconEye />}
                            active={componentPanels.view}
                            tooltip="View mode"
                            onClick={() => toggleComponentPanel('view')}
                        />
                        <LemonButton
                            size="xsmall"
                            icon={<IconPencil />}
                            active={componentPanels.edit}
                            tooltip="Edit mode"
                            onClick={() => toggleComponentPanel('edit')}
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

function InsertMenu({
    query,
    commands,
    targetNodeId,
    onClose,
}: {
    query: string
    commands: InsertCommand[]
    targetNodeId: string
    onClose: () => void
}): JSX.Element {
    const normalizedQuery = query.trim().toLowerCase()
    const filteredCommands = commands.filter((command) => {
        if (!normalizedQuery) {
            return true
        }
        return `${command.label} ${command.category} ${command.description ?? ''}`
            .toLowerCase()
            .includes(normalizedQuery)
    })
    const commandsByCategory = filteredCommands.reduce<Record<string, InsertCommand[]>>((accumulator, command) => {
        accumulator[command.category] = [...(accumulator[command.category] ?? []), command]
        return accumulator
    }, {})

    return (
        <div className="MarkdownNotebook__insert-menu">
            <div className="MarkdownNotebook__insert-menu-header">
                <span>Add to notebook</span>
                <LemonButton size="xsmall" onClick={onClose}>
                    Close
                </LemonButton>
            </div>
            {Object.entries(commandsByCategory).map(([category, categoryCommands]) => (
                <div className="MarkdownNotebook__insert-category" key={category}>
                    <h5>{category}</h5>
                    <div className="MarkdownNotebook__insert-grid">
                        {categoryCommands.map((command) => (
                            <button
                                className="MarkdownNotebook__insert-item"
                                key={command.key}
                                type="button"
                                onClick={() => {
                                    command.run(targetNodeId)
                                    onClose()
                                }}
                            >
                                {command.icon ? <span>{command.icon}</span> : null}
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

function buildInsertCommands(
    registry: NotebookComponentRegistry,
    replaceNode: (nodeId: string, nextNode: NotebookBlockNode) => void,
    insertNodeAfter: (nodeId: string, nextNode: NotebookBlockNode) => void,
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
): InsertCommand[] {
    const insertComponent = (
        targetNodeId: string,
        tagName: string,
        props: NotebookComponentProps,
        replaceTarget: boolean = true
    ): void => {
        const node: NotebookComponentBlockNode = {
            id: makeEmptyParagraph(`component-${tagName}`).id,
            type: 'component',
            tagName,
            props,
        }

        if (replaceTarget) {
            replaceNode(targetNodeId, node)
            return
        }
        insertNodeAfter(targetNodeId, node)
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
            key: 'query-sql',
            label: 'SQL query',
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
    ]

    const textCommands: InsertCommand[] = [
        {
            key: 'text-heading-1',
            label: 'Heading 1',
            category: 'Text',
            run: (targetNodeId) => setTargetBlockStyle(updateNode, targetNodeId, 1),
        },
        {
            key: 'text-heading-2',
            label: 'Heading 2',
            category: 'Text',
            run: (targetNodeId) => setTargetBlockStyle(updateNode, targetNodeId, 2),
        },
        {
            key: 'text-paragraph',
            label: 'Text',
            category: 'Text',
            run: (targetNodeId) => setTargetBlockStyle(updateNode, targetNodeId, 'paragraph'),
        },
    ]

    const componentCommands = Object.values(registry.components)
        .filter((definition) => definition.tagName !== 'Query')
        .map<InsertCommand>((definition) => ({
            key: `component-${definition.tagName}`,
            label: definition.label,
            category: definition.category,
            description: definition.description,
            icon: definition.icon as JSX.Element | undefined,
            run: (targetNodeId) =>
                insertComponent(
                    targetNodeId,
                    definition.tagName,
                    typeof definition.defaultProps === 'function'
                        ? definition.defaultProps()
                        : (definition.defaultProps ?? {})
                ),
        }))

    return [...textCommands, ...queryCommands, ...componentCommands]
}

function setTargetBlockStyle(
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void,
    targetNodeId: string,
    style: 'paragraph' | 1 | 2
): void {
    updateNode(targetNodeId, (node) => {
        if (!isTextBlockNode(node)) {
            return node
        }
        if (typeof style === 'number') {
            return { ...node, type: 'heading', level: style }
        }
        return { ...node, type: 'paragraph', level: undefined }
    })
}

function renderInlineNodes(nodes: NotebookInlineNode[]): ReactNode {
    return nodes.map((node, index) => {
        if (node.type === 'hardBreak') {
            return <br key={index} />
        }

        return applyMarkElements(node.text, node.marks ?? [], index)
    })
}

function applyMarkElements(text: string, marks: NotebookInlineMark[], key: Key): ReactNode {
    return marks.reduce<ReactNode>(
        (children, mark) => {
            if (mark.type === 'bold') {
                return <strong>{children}</strong>
            }
            if (mark.type === 'italic') {
                return <em>{children}</em>
            }
            if (mark.type === 'underline') {
                return <u>{children}</u>
            }
            if (mark.type === 'code') {
                return <code>{children}</code>
            }
            return <Link to={mark.href}>{children}</Link>
        },
        <span key={key}>{text}</span>
    )
}

function isTextBlockNode(node: NotebookBlockNode): node is NotebookTextBlockNode {
    return node.type === 'paragraph' || node.type === 'heading' || node.type === 'blockquote'
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
