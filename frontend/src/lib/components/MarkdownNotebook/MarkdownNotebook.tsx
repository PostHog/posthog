import './MarkdownNotebook.scss'

import clsx from 'clsx'
import {
    ClipboardEvent as ReactClipboardEvent,
    Component,
    DragEvent as ReactDragEvent,
    FocusEvent as ReactFocusEvent,
    FormEvent,
    Fragment,
    KeyboardEvent,
    MouseEvent as ReactMouseEvent,
    ReactNode,
    Suspense,
    useCallback,
    useEffect,
    useId,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from 'react'

import { IconCode, IconComment, IconDrag } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { downloadFile } from 'lib/utils/dom'
import { lazyWithRetry } from 'lib/utils/lazyWithRetry'

// Monaco is heavy, so the markdown source editor only loads when the source drawer opens.
const LazyCodeEditor = lazyWithRetry(() =>
    import('lib/monaco/CodeEditor').then((module) => ({ default: module.CodeEditor }))
)

import { mergeNotebookMarkdownChanges } from './collaboration'
import {
    ComponentPanelCacheEntry,
    ComponentPanelVisibility,
    DEFAULT_COMPONENT_PANEL_VISIBILITY,
    getComponentPanelVisibility,
    getInsertedComponentPanelVisibility,
    shouldPersistComponentPanelProps,
    withPersistedComponentPanelProps,
} from './componentPanels'
import {
    MarkdownNotebookTextSurface,
    areNotebookDocumentsEqual,
    ensureEditableNotebookDocument,
    getAskAIInlineNotebookQuery,
    getAskAISelectionQuery,
    getClipboardMarkdown,
    getHistoryRestoreSelection,
    getInlineInsertMenuQuery,
    getMarkdownNotebookVisualGroups,
    getNotebookStringProp,
    getPromptSource,
    getSlashCommandQuery,
    getTaskItemShortcut,
    getTextBlockShortcutReplacement,
    hasNotebookContent,
    getDiscussionCommentRefId,
    isBlankInsertMenuButtonRow,
    isDiscussionCommentNode,
    isGroupedBlockquoteNode,
    isPromptComponentNode,
    isTextBlockNode,
    makeEmptyNotebookTitle,
    removeNotebookNodesWithRefCleanup,
    stripNotebookRefMarksFromNodes,
    mapRestoreSelectionThroughDocumentChange,
    readSystemClipboardText,
    rekeyNotebookNodes,
    serializeNotebookNodes,
    setClipboardMarkdown,
    setsEqual,
    textBlocksShareContinuationStyle,
    updateNotebookCodeBlockText,
    writeSystemClipboardText,
} from './documentModel'
import {
    findTextPosition,
    getClosestEditableBlockElement,
    getCollapsedSelectionRange,
    getCollapsedSelectionRestoreRequest,
    getComponentNodeForSelection,
    getElementForNode,
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
    inputEventCrossesInlineEditableBoundary,
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
    InsertCommand,
    InsertMenuPosition,
    InsertMenuSelectionDirection,
    InsertMenuState,
    MarkdownNotebookInsertMenuApi,
    MAX_UNDO_HISTORY_ENTRIES,
    NOTEBOOK_TITLE_PLACEHOLDER,
    RestoreSelectionRequest,
    RestoreTextRange,
    TableCellPosition,
    TextBlockStyle,
    TextSelectionPointerStartEvent,
    TextSelectionPointerState,
} from './editorTypes'
import {
    FormattingToolbar,
    getFloatingToolbarLinkHref,
    getSelectedBlockStyle,
    getSelectedBlocksQuoted,
} from './FormattingToolbar'
import { markNotebookNodeFreshlyInserted } from './freshlyInserted'
import {
    InlineMarkSelection,
    areInlineSelectionsFullyMarked,
    plainTextToInlineNodes,
    setInlineLinkMark,
    setInlineMark,
    setInlineRefMark,
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
    getInsertMenuOptionDomId,
    getInsertMenuPosition,
    getNextInsertMenuSelectedIndex,
} from './InsertMenu'
import {
    deleteListItemSelectionRange,
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
import { NOTEBOOK_AI_WRITING_PLACEHOLDER } from './notebookAI'
import {
    NotebookOperation,
    applyNotebookOperations,
    diffNotebookDocuments,
    rebaseNotebookOperationStack,
} from './operations'
import { reconcileNotebookDocuments } from './reconcile'
import {
    getMarkdownNotebookComponentDefinition,
    getMarkdownNotebookDefaultRegistry,
    mergeMarkdownNotebookRegistries,
} from './registry'
import {
    MarkdownNotebookCaretPosition,
    RemoteCaretOverlay,
    RemoteNotebookCaret,
    getFocusedBlockCaretPosition,
    getMarkdownNotebookCaretPosition,
    mapRemoteCaretPositionThroughDocumentChange,
} from './remoteCarets'
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
    NotebookCodeBlockNode,
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
import { cloneNotebookNode, getInlineText, getNodeFingerprint, normalizeInlineNodes } from './utils'

export type MarkdownNotebookProps = {
    value: string
    onChange?: (value: string) => void
    onAskAI?: (request: MarkdownNotebookAskAIRequest) => void
    isAskAIDisabled?: boolean
    createAIConversationId?: () => string
    mode?: NotebookMode
    registry?: NotebookComponentRegistry
    /** Caller-supplied insert-menu commands. Receives an API for inserting blocks so the command's
     * behavior (e.g. opening a picker modal) and labeling stay in the caller, not this component. */
    extraInsertCommands?: (api: MarkdownNotebookInsertMenuApi) => InsertCommand[]
    remoteValue?: string
    /** Notebook version `remoteValue` corresponds to, for version-aware caret mapping. */
    remoteVersion?: number
    deferRemoteValue?: boolean
    clientId?: string
    onConflict?: (conflicts: NotebookCollaborationConflict[]) => void
    onInteractionStateChange?: (isInteractionActive: boolean) => void
    /** Carets of other clients editing this notebook, rendered as a positioned overlay. */
    remoteCarets?: RemoteNotebookCaret[]
    /** Reports the local caret whenever it moves; null when the selection leaves the notebook. */
    onCaretChange?: (position: MarkdownNotebookCaretPosition | null) => void
    initialInsertMenu?: { nodeIndex?: number; query?: string }
    /** Converts external content (dropped or pasted files, dragged app resources or URLs) into
     * blocks inserted at the drop/caret position. Return null to ignore the transfer; return a
     * promise when conversion needs async work (e.g. file uploads) — the insert position is
     * captured up front. */
    convertExternalDataTransferToNodes?: (
        dataTransfer: DataTransfer
    ) => NotebookBlockNode[] | Promise<NotebookBlockNode[] | null> | null
    focusAIPromptRequest?: number
    aiWritingNodeIndexes?: number[]
    placeholder?: string
    className?: string
    autoFocus?: boolean
    showDebug?: boolean
    debugOpen?: boolean
    onDebugOpenChange?: (isOpen: boolean) => void
    'data-attr'?: string
}

export type MarkdownNotebookAskAIRequest = {
    conversationId: string
    query: string
    source: 'slash' | 'selection'
    responseNodeId: string
    responseNodeIndex: number
    responseMarker: string
    markdown: string
    markdownWithResponse: string
    selectedMarkdown?: string
    selectedRefId?: string
}

type CommitDocumentOptions = {
    addToHistory?: boolean
    historyOperations?: NotebookOperation[]
    /** Set when the commit applies a remote merge: the notebook version being merged in.
     * Remote caret pings already at this version reflect the change and must not be remapped. */
    remoteMergeVersion?: number
}

type RemoteCaretAnchor = {
    caret: RemoteNotebookCaret
    /** The position as the sender reported it — a new ping re-anchors, a heartbeat does not. */
    source: MarkdownNotebookCaretPosition
    /** The position remapped through local document changes since the ping. */
    position: MarkdownNotebookCaretPosition
}

type NotebookHistoryEntry = {
    /** Operations that revert the edit; the newest entry applies to the current document. */
    ops: NotebookOperation[]
    /** Where the cursor was while this document was current, so undo/redo can return to the edit point. */
    selection: RestoreSelectionRequest | null
    /** Wall-clock time of the last edit folded into this entry, for grouping typing runs. */
    editedAt: number
    /** Set when the entry edits a single block, enabling typing-run coalescing. */
    coalesceNodeId: string | null
}

type NotebookHistoryState = {
    undo: NotebookHistoryEntry[]
    redo: NotebookHistoryEntry[]
}

/** Consecutive single-block edits within this window fold into one undo step. */
const UNDO_TYPING_GROUP_MS = 1000

/** How many recent local serializations to remember for save-echo detection. Must comfortably
 * cover the keystrokes that can land between a save being sent and its response echoing back. */
const MAX_TRACKED_LOCAL_SNAPSHOTS = 100
const EMPTY_AI_WRITING_NODE_INDEX_SET = new Set<number>()

function createDefaultAIConversationId(): string {
    if (typeof window !== 'undefined' && window.crypto?.randomUUID) {
        return window.crypto.randomUUID()
    }
    return makeEmptyParagraph('ai-conversation').id
}

/** Below this container width, comment threads render inline instead of in the margin. */
const COMMENT_GUTTER_MIN_CONTAINER_WIDTH_PX = 960

/** Vertical spacing between stacked comment threads in the gutter. */
const GUTTER_COMMENT_GAP_PX = 8

/** Short, human-skimmable id shared by a `<ref>` highlight and its `<Comment ref>` thread. */
function createNotebookRefId(): string {
    if (typeof window !== 'undefined' && window.crypto?.randomUUID) {
        return window.crypto.randomUUID().replace(/-/g, '').slice(0, 8)
    }
    return Math.random().toString(36).slice(2, 10)
}

function getAIWritingPlaceholderNodeIds(nodes: NotebookBlockNode[]): Set<string> {
    const nodeIds = new Set<string>()
    for (const node of nodes) {
        if (node.type === 'paragraph' && getInlineText(node.children) === NOTEBOOK_AI_WRITING_PLACEHOLDER) {
            nodeIds.add(node.id)
        }
    }
    return nodeIds
}

function getLatestEmptyAIPromptNodeId(nodes: NotebookBlockNode[]): string | null {
    for (let index = nodes.length - 1; index >= 0; index--) {
        const node = nodes[index]
        if (node && isPromptComponentNode(node) && !(getNotebookStringProp(node.props.question) ?? '').trim()) {
            return node.id
        }
    }
    return null
}

function getComponentNodeUpdateHistoryOperations(
    nodes: NotebookBlockNode[],
    index: number,
    previousNode: NotebookBlockNode,
    nextNode: NotebookBlockNode | null
): NotebookOperation[] | undefined {
    if (previousNode.type !== 'component' && nextNode?.type !== 'component') {
        return undefined
    }

    const previousAfterId = index === 0 ? null : (nodes[index - 1]?.id ?? null)
    if (!nextNode) {
        return [{ type: 'insert_block', afterId: previousAfterId, node: cloneNotebookNode(previousNode) }]
    }

    if (
        previousNode.type === 'component' &&
        nextNode.type === 'component' &&
        areComponentNodesEquivalent(previousNode, nextNode)
    ) {
        return []
    }

    if (previousNode.id === nextNode.id) {
        return [{ type: 'replace_block', nodeId: previousNode.id, node: cloneNotebookNode(previousNode) }]
    }

    return [
        { type: 'delete_block', nodeId: nextNode.id },
        { type: 'insert_block', afterId: previousAfterId, node: cloneNotebookNode(previousNode) },
    ]
}

function areComponentNodesEquivalent(
    previousNode: NotebookComponentBlockNode,
    nextNode: NotebookComponentBlockNode
): boolean {
    return (
        previousNode.id === nextNode.id &&
        previousNode.raw === nextNode.raw &&
        getNodeFingerprint(previousNode) === getNodeFingerprint(nextNode) &&
        componentNodeErrorsKey(previousNode) === componentNodeErrorsKey(nextNode)
    )
}

function componentNodeErrorsKey(node: NotebookComponentBlockNode): string {
    return node.errors?.join('\n') ?? ''
}

/** Input types whose browser default edits the DOM across the current selection/target range. */
const NATIVE_RANGE_EDIT_INPUT_TYPES = new Set([
    'insertText',
    'insertParagraph',
    'insertLineBreak',
    'insertFromPaste',
    'insertFromPasteAsQuotation',
    'insertFromDrop',
    'insertFromYank',
    'insertReplacementText',
    'insertTranspose',
    'deleteContent',
    'deleteContentBackward',
    'deleteContentForward',
    'deleteWordBackward',
    'deleteWordForward',
    'deleteSoftLineBackward',
    'deleteSoftLineForward',
    'deleteHardLineBackward',
    'deleteHardLineForward',
    'deleteEntireSoftLine',
    'deleteByCut',
    'deleteByDrag',
])

/** A debug recording session: JSONL entries downloaded as a .log file on stop. */
type NotebookDebugLog = {
    startedAt: number
    entries: string[]
    lastSelectionSummary: string | null
}

function truncateForDebugLog(value: string | null | undefined, maxLength: number): string | undefined {
    if (value === null || value === undefined) {
        return undefined
    }
    return value.length > maxLength ? `${value.slice(0, maxLength)}…(${String(value.length)} chars)` : value
}

function getDebugTargetInfo(target: EventTarget | null): Record<string, unknown> {
    if (!(target instanceof Element)) {
        return {}
    }
    const block = target.closest('[data-markdown-notebook-node-id]')
    const className = typeof target.className === 'string' ? target.className.split(' ')[0] : ''
    return {
        target: `${target.tagName.toLowerCase()}${className ? `.${className}` : ''}`,
        ...(block instanceof HTMLElement && block.dataset.markdownNotebookNodeId
            ? { nodeId: block.dataset.markdownNotebookNodeId }
            : {}),
    }
}

function getDebugSelectionSummary(): Record<string, unknown> {
    const selection = window.getSelection()
    if (!selection || selection.rangeCount === 0) {
        return { selection: null }
    }

    const describePoint = (node: Node | null, offset: number): Record<string, unknown> => {
        const element = node instanceof Element ? node : node?.parentElement
        const block = element?.closest('[data-markdown-notebook-node-id]')
        return {
            nodeId: block instanceof HTMLElement ? block.dataset.markdownNotebookNodeId : undefined,
            offset,
        }
    }

    return {
        collapsed: selection.isCollapsed,
        anchor: describePoint(selection.anchorNode, selection.anchorOffset),
        focus: describePoint(selection.focusNode, selection.focusOffset),
        text: truncateForDebugLog(selection.toString(), 200),
    }
}

// Debug recordings currently in flight, so a crash anywhere in the editor can flush them
// before the component (and its refs) unmounts.
const activeDebugLogCrashFlushers = new Set<(error: unknown) => void>()

function flushMarkdownNotebookDebugLogsOnCrash(error: unknown): void {
    for (const flush of activeDebugLogCrashFlushers) {
        flush(error)
    }
}

type MarkdownNotebookCrashReporterState = { error: Error | null; reported: boolean }

/**
 * Downloads any in-flight debug recording before a render/commit crash unmounts the editor.
 * The error is rethrown so the surrounding error boundary still renders its usual fallback —
 * by then the log download has already been triggered.
 */
class MarkdownNotebookCrashReporter extends Component<{ children: ReactNode }, MarkdownNotebookCrashReporterState> {
    override state: MarkdownNotebookCrashReporterState = { error: null, reported: false }

    static getDerivedStateFromError(error: Error): Partial<MarkdownNotebookCrashReporterState> {
        return { error }
    }

    override componentDidCatch(error: Error): void {
        flushMarkdownNotebookDebugLogsOnCrash(error)
        this.setState({ reported: true })
    }

    override render(): ReactNode {
        if (this.state.error) {
            if (this.state.reported) {
                throw this.state.error
            }
            // One empty pass: componentDidCatch runs after it commits, flushes the log, and
            // flips `reported` so the next render rethrows into the surrounding boundary.
            return null
        }
        return this.props.children
    }
}

export function MarkdownNotebook(props: MarkdownNotebookProps): JSX.Element {
    return (
        <MarkdownNotebookCrashReporter>
            <MarkdownNotebookEditor {...props} />
        </MarkdownNotebookCrashReporter>
    )
}

function MarkdownNotebookEditor({
    value,
    onChange,
    onAskAI,
    isAskAIDisabled: isAIPromptSubmitDisabled = false,
    createAIConversationId = createDefaultAIConversationId,
    mode = 'edit',
    registry,
    extraInsertCommands,
    remoteValue,
    remoteVersion,
    deferRemoteValue = false,
    onConflict,
    onInteractionStateChange,
    remoteCarets,
    onCaretChange,
    initialInsertMenu,
    convertExternalDataTransferToNodes,
    focusAIPromptRequest,
    aiWritingNodeIndexes,
    placeholder = 'Start writing...',
    className,
    autoFocus = false,
    showDebug = false,
    debugOpen,
    onDebugOpenChange,
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
    const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null)
    const [dropBoundaryIndex, setDropBoundaryIndex] = useState<number | null>(null)
    const [isExternalDragOver, setIsExternalDragOver] = useState(false)
    /** Whether the in-flight drag started inside this editor (native text/link drags included). */
    const canvasDragOriginRef = useRef(false)
    const [selectedComponentNodeIds, setSelectedComponentNodeIds] = useState<Set<string>>(() => new Set())
    const [componentPanelCache, setComponentPanelCache] = useState<Record<string, ComponentPanelCacheEntry>>({})
    const [internalDebugOpen, setInternalDebugOpen] = useState(false)
    const isDebugOpen = debugOpen ?? internalDebugOpen
    const [isDebugLogging, setIsDebugLogging] = useState(false)
    const debugLogRef = useRef<NotebookDebugLog | null>(null)
    // Margin layout needs the container to fit the text column plus the full comment
    // gutter; below that, threads flow inline instead of hanging off-screen.
    const [fitsCommentGutter, setFitsCommentGutter] = useState(true)
    const [debugMarkdown, setDebugMarkdown] = useState(() => serializeMarkdownNotebook(document))
    const debugDrawerId = useId()
    const insertMenuDomId = useId()
    const notebookRef = useRef<HTMLDivElement | null>(null)
    const mainRef = useRef<HTMLDivElement | null>(null)
    const canvasRef = useRef<HTMLDivElement | null>(null)
    const documentRef = useRef(document)
    const blockRefs = useRef<Record<string, HTMLElement | null>>({})
    const listItemRefs = useRef<Record<string, HTMLElement | null>>({})
    const tableCellRefs = useRef<Record<string, HTMLElement | null>>({})
    const rootEditableInputHtmlByNodeIdRef = useRef<Record<string, string>>({})
    const blockDragNodeIdRef = useRef<string | null>(null)
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
    // Recent local serializations, oldest first. A remote update matching one of these is the
    // echo of our own save — already contained in the local state, so merging it back in would
    // duplicate the overlapping insertions.
    const localSnapshotsRef = useRef<string[]>([value])
    // The three-way merge base: the last server state local edits were derived from.
    const lastBaseValueRef = useRef(remoteValue ?? value)
    const lastRemoteValueRef = useRef(remoteValue)
    const pendingRemoteValueRef = useRef<string | null>(null)
    const remoteVersionRef = useRef(remoteVersion)
    remoteVersionRef.current = remoteVersion
    const remoteCaretAnchorsRef = useRef<Record<string, RemoteCaretAnchor>>({})
    const [adjustedRemoteCarets, setAdjustedRemoteCarets] = useState<RemoteNotebookCaret[] | undefined>(remoteCarets)
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

    const hasDiscussionComments = useMemo(() => document.nodes.some(isDiscussionCommentNode), [document])
    const aiWritingNodeIndexSet = useMemo(
        () => (aiWritingNodeIndexes?.length ? new Set(aiWritingNodeIndexes) : EMPTY_AI_WRITING_NODE_INDEX_SET),
        [aiWritingNodeIndexes]
    )

    useLayoutEffect(() => {
        const element = mainRef.current
        if (!hasDiscussionComments || !element || typeof ResizeObserver === 'undefined') {
            return
        }

        const updateFitsCommentGutter = (): void => {
            setFitsCommentGutter(element.clientWidth >= COMMENT_GUTTER_MIN_CONTAINER_WIDTH_PX)
        }
        updateFitsCommentGutter()
        const resizeObserver = new ResizeObserver(updateFitsCommentGutter)
        resizeObserver.observe(element)
        return () => resizeObserver.disconnect()
    }, [hasDiscussionComments])

    const logDebugEntry = useCallback((type: string, payload: Record<string, unknown> = {}): void => {
        const log = debugLogRef.current
        if (!log) {
            return
        }
        log.entries.push(JSON.stringify({ t: Date.now() - log.startedAt, type, ...payload }))
    }, [])

    const startDebugLogging = (): void => {
        debugLogRef.current = { startedAt: Date.now(), entries: [], lastSelectionSummary: null }
        logDebugEntry('start', {
            markdown: lastSerializedValueRef.current,
            remoteVersion: remoteVersionRef.current,
            mode,
            userAgent: typeof navigator === 'undefined' ? undefined : navigator.userAgent,
        })
        setIsDebugLogging(true)
    }

    const downloadDebugLog = useCallback((log: NotebookDebugLog): void => {
        // downloadFile appends the anchor to the DOM and defers the object-URL revoke, which
        // Firefox needs for the download to actually start.
        downloadFile(
            new File(
                [log.entries.join('\n') + '\n'],
                `markdown-notebook-debug-${new Date().toISOString().replace(/[:.]/g, '-')}.log`,
                { type: 'text/plain' }
            )
        )
    }, [])

    const stopDebugLoggingAndDownload = (): void => {
        const log = debugLogRef.current
        logDebugEntry('stop', { markdown: lastSerializedValueRef.current })
        debugLogRef.current = null
        setIsDebugLogging(false)
        if (!log) {
            return
        }

        downloadDebugLog(log)
    }

    // A crash can unmount the editor or leave its DOM unusable, which would silently discard
    // an in-flight recording — the moment the editor did something worth debugging. Download
    // the log immediately instead of losing it.
    const flushDebugLogOnCrash = useCallback(
        (error: unknown): void => {
            const log = debugLogRef.current
            if (!log) {
                return
            }

            logDebugEntry('crash', {
                error: error instanceof Error ? `${error.name}: ${error.message}` : String(error),
                stack: error instanceof Error ? truncateForDebugLog(error.stack, 4000) : undefined,
                markdown: lastSerializedValueRef.current,
            })
            debugLogRef.current = null
            setIsDebugLogging(false)
            downloadDebugLog(log)
        },
        [downloadDebugLog, logDebugEntry]
    )

    // While recording, an uncaught error anywhere flushes the log: crashes in event handlers
    // and DOM listeners never reach the crash reporter boundary below. Unhandled rejections
    // are recorded but don't end the session — they are usually background noise (a failed
    // fetch), not an editor crash.
    useEffect(() => {
        if (!isDebugLogging) {
            return
        }

        const handleWindowError = (event: ErrorEvent): void => {
            flushDebugLogOnCrash(event.error ?? event.message)
        }
        const handleUnhandledRejection = (event: PromiseRejectionEvent): void => {
            const reason: unknown = event.reason
            logDebugEntry('unhandledrejection', {
                error: reason instanceof Error ? `${reason.name}: ${reason.message}` : String(reason),
            })
        }
        activeDebugLogCrashFlushers.add(flushDebugLogOnCrash)
        window.addEventListener('error', handleWindowError)
        window.addEventListener('unhandledrejection', handleUnhandledRejection)
        return () => {
            activeDebugLogCrashFlushers.delete(flushDebugLogOnCrash)
            window.removeEventListener('error', handleWindowError)
            window.removeEventListener('unhandledrejection', handleUnhandledRejection)
        }
    }, [isDebugLogging, flushDebugLogOnCrash, logDebugEntry])

    // While recording, capture-phase listeners mirror every keyboard, mouse, input, and
    // clipboard event into the log, plus deduplicated selection snapshots — together with
    // the commit entries this reconstructs an editing session for offline debugging.
    useEffect(() => {
        const root = notebookRef.current
        if (!isDebugLogging || !root) {
            return
        }

        const logKeyboardEvent = (event: globalThis.KeyboardEvent): void => {
            logDebugEntry(event.type, {
                key: event.key,
                code: event.code,
                meta: event.metaKey || undefined,
                ctrl: event.ctrlKey || undefined,
                alt: event.altKey || undefined,
                shift: event.shiftKey || undefined,
                repeat: event.repeat || undefined,
                ...getDebugTargetInfo(event.target),
            })
        }
        const logMouseEvent = (event: globalThis.MouseEvent): void => {
            logDebugEntry(event.type, {
                button: event.button,
                x: Math.round(event.clientX),
                y: Math.round(event.clientY),
                detail: event.detail,
                ...getDebugTargetInfo(event.target),
            })
        }
        const logInputEvent = (event: Event): void => {
            const inputEvent = event as InputEvent
            logDebugEntry(event.type, {
                inputType: inputEvent.inputType,
                data: truncateForDebugLog(inputEvent.data, 200),
                ...getDebugTargetInfo(event.target),
            })
        }
        const logClipboardEvent = (event: globalThis.ClipboardEvent): void => {
            logDebugEntry(event.type, {
                text: truncateForDebugLog(event.clipboardData?.getData('text/plain'), 500),
                ...getDebugTargetInfo(event.target),
            })
        }
        const logSelectionChange = (): void => {
            const log = debugLogRef.current
            if (!log) {
                return
            }
            const summary = getDebugSelectionSummary()
            const serializedSummary = JSON.stringify(summary)
            if (serializedSummary === log.lastSelectionSummary) {
                return
            }
            log.lastSelectionSummary = serializedSummary
            logDebugEntry('selectionchange', summary)
        }

        // `beforeinput` is missing from HTMLElementEventMap in our TS lib, hence the
        // EventListener casts.
        const listenersByEventType: [string, EventListener][] = [
            ['keydown', logKeyboardEvent as EventListener],
            ['keyup', logKeyboardEvent as EventListener],
            ['mousedown', logMouseEvent as EventListener],
            ['mouseup', logMouseEvent as EventListener],
            ['click', logMouseEvent as EventListener],
            ['dblclick', logMouseEvent as EventListener],
            ['contextmenu', logMouseEvent as EventListener],
            ['beforeinput', logInputEvent],
            ['input', logInputEvent],
            ['cut', logClipboardEvent as EventListener],
            ['copy', logClipboardEvent as EventListener],
            ['paste', logClipboardEvent as EventListener],
        ]
        listenersByEventType.forEach(([type, listener]) => root.addEventListener(type, listener, true))
        window.document.addEventListener('selectionchange', logSelectionChange)

        return () => {
            listenersByEventType.forEach(([type, listener]) => root.removeEventListener(type, listener, true))
            window.document.removeEventListener('selectionchange', logSelectionChange)
        }
    }, [isDebugLogging, logDebugEntry])

    // Stack margin comment threads in the gutter so neighbors never overlap: each thread
    // starts at its anchor row's top unless the previous thread reaches below it, in which
    // case it is pushed down just past that thread.
    useLayoutEffect(() => {
        if (!hasDiscussionComments || !fitsCommentGutter) {
            return
        }

        const commentNodeIds = document.nodes.filter(isDiscussionCommentNode).map((node) => node.id)
        const layoutGutterComments = (): void => {
            let nextAvailableTop = -Infinity
            for (const nodeId of commentNodeIds) {
                const shell = blockRefs.current[nodeId]
                const row = shell?.closest('.MarkdownNotebook__row')
                if (!shell || !(row instanceof HTMLElement)) {
                    continue
                }
                const rowTop = row.getBoundingClientRect().top
                const offset = Math.max(0, nextAvailableTop - rowTop)
                shell.style.top = `${offset}px`
                nextAvailableTop = rowTop + offset + shell.offsetHeight + GUTTER_COMMENT_GAP_PX
            }
        }

        layoutGutterComments()
        if (typeof ResizeObserver === 'undefined') {
            return
        }
        const resizeObserver = new ResizeObserver(layoutGutterComments)
        if (canvasRef.current) {
            resizeObserver.observe(canvasRef.current)
        }
        commentNodeIds.forEach((nodeId) => {
            const shell = blockRefs.current[nodeId]
            if (shell) {
                resizeObserver.observe(shell)
            }
        })
        return () => {
            resizeObserver.disconnect()
            commentNodeIds.forEach((nodeId) => {
                const shell = blockRefs.current[nodeId]
                if (shell) {
                    shell.style.top = ''
                }
            })
        }
    }, [document, hasDiscussionComments, fitsCommentGutter])

    const clearFloatingToolbarRevealTimeout = useCallback((): void => {
        if (floatingToolbarRevealTimeoutRef.current === null) {
            return
        }

        window.clearTimeout(floatingToolbarRevealTimeoutRef.current)
        floatingToolbarRevealTimeoutRef.current = null
    }, [])

    const setDebugOpen = useCallback(
        (nextOpen: boolean | ((isOpen: boolean) => boolean)): void => {
            const resolvedNextOpen = typeof nextOpen === 'function' ? nextOpen(isDebugOpen) : nextOpen
            if (debugOpen === undefined) {
                setInternalDebugOpen(resolvedNextOpen)
            }
            onDebugOpenChange?.(resolvedNextOpen)
        },
        [debugOpen, isDebugOpen, onDebugOpenChange]
    )

    useEffect(() => {
        if (!showDebug) {
            setDebugOpen(false)
        }
    }, [setDebugOpen, showDebug])

    const mapRemoteCaretAnchors = useCallback(
        (previousDocument: NotebookDocument, nextDocument: NotebookDocument, remoteMergeVersion?: number): void => {
            const anchors = remoteCaretAnchorsRef.current
            const clientIds = Object.keys(anchors)
            if (!clientIds.length) {
                return
            }

            let didChange = false
            for (const clientIdKey of clientIds) {
                const anchor = anchors[clientIdKey]
                // A ping at or past the merged version already reflects the incoming change.
                if (
                    remoteMergeVersion !== undefined &&
                    anchor.caret.version !== undefined &&
                    anchor.caret.version >= remoteMergeVersion
                ) {
                    continue
                }
                const mapped = mapRemoteCaretPositionThroughDocumentChange(
                    anchor.position,
                    previousDocument,
                    nextDocument
                )
                if (mapped !== anchor.position) {
                    anchors[clientIdKey] = { ...anchor, position: mapped }
                    didChange = true
                }
            }
            if (didChange) {
                setAdjustedRemoteCarets(
                    Object.values(anchors).map((anchor) => ({ ...anchor.caret, position: anchor.position }))
                )
            }
        },
        []
    )

    const rebaseHistoryThroughDocumentChange = useCallback(
        (previousDocument: NotebookDocument, nextDocument: NotebookDocument): void => {
            const incomingOps = diffNotebookDocuments(previousDocument, nextDocument)
            if (!incomingOps.length) {
                return
            }
            historyRef.current = {
                undo: rebaseNotebookOperationStack(historyRef.current.undo, incomingOps),
                redo: rebaseNotebookOperationStack(historyRef.current.redo, incomingOps),
            }
        },
        []
    )

    useEffect(() => {
        if (value === lastSerializedValueRef.current) {
            return
        }

        const restoreSelectionRequest = notebookRef.current
            ? getCollapsedSelectionRestoreRequest(window.getSelection(), notebookRef.current)
            : null
        const previousDocument = documentRef.current
        const reconciledDocument = ensureEditableNotebookDocument(
            reconcileNotebookDocuments(previousDocument, parseMarkdownNotebook(value)).document
        )
        // An external value change (artifact apply, restore, AI edit) rebases the undo
        // history over the incoming operations instead of clearing it, so CMD+Z keeps
        // reverting only this user's edits.
        rebaseHistoryThroughDocumentChange(previousDocument, reconciledDocument)
        mapRemoteCaretAnchors(previousDocument, reconciledDocument)
        logDebugEntry('external-value', { markdown: value })
        documentRef.current = reconciledDocument
        setDocument(reconciledDocument)
        if (restoreSelectionRequest) {
            // Map the caret through the incoming change so it stays at the same place in
            // the text, not at the same numeric offset.
            restoreSelectionRef.current = mapRestoreSelectionThroughDocumentChange(
                restoreSelectionRequest,
                previousDocument,
                reconciledDocument
            )
        }
        setDebugMarkdown(value)
        // The base is intentionally left untouched: an external `value` change is a local-side
        // update (artifact apply, restore), so the last synced server state remains the merge base.
        lastSerializedValueRef.current = value
        trackLocalSnapshot(value)
        // oxlint-disable-next-line exhaustive-deps
    }, [value])

    useLayoutEffect(() => {
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

    const captureHistorySelection = useCallback((): RestoreSelectionRequest | null => {
        return notebookRef.current
            ? getCollapsedSelectionRestoreRequest(window.getSelection(), notebookRef.current)
            : null
    }, [])

    const pushHistoryEntry = useCallback(
        (
            previousDocument: NotebookDocument,
            nextDocument: NotebookDocument,
            historyOperations?: NotebookOperation[]
        ): void => {
            const inverseOps = historyOperations ?? diffNotebookDocuments(nextDocument, previousDocument)
            if (!inverseOps.length) {
                return
            }

            const now = Date.now()
            const onlyOp = inverseOps.length === 1 ? inverseOps[0] : null
            const coalesceNodeId =
                onlyOp && (onlyOp.type === 'text' || onlyOp.type === 'replace_block') ? onlyOp.nodeId : null
            const lastEntry = historyRef.current.undo[historyRef.current.undo.length - 1]
            if (
                coalesceNodeId &&
                lastEntry &&
                lastEntry.coalesceNodeId === coalesceNodeId &&
                now - lastEntry.editedAt < UNDO_TYPING_GROUP_MS &&
                !historyRef.current.redo.length
            ) {
                // Fold the typing run into the open entry. For wholesale block replaces the
                // older inverse already restores the pre-run content, so the new one is moot.
                if (!(onlyOp?.type === 'replace_block' && lastEntry.ops.every((op) => op.type === 'replace_block'))) {
                    lastEntry.ops = [...inverseOps, ...lastEntry.ops]
                }
                lastEntry.editedAt = now
                return
            }

            historyRef.current = {
                undo: [
                    ...historyRef.current.undo.slice(-(MAX_UNDO_HISTORY_ENTRIES - 1)),
                    { ops: inverseOps, selection: captureHistorySelection(), editedAt: now, coalesceNodeId },
                ],
                redo: [],
            }
        },
        [captureHistorySelection]
    )

    const trackLocalSnapshot = useCallback((serialized: string): void => {
        const snapshots = localSnapshotsRef.current
        if (snapshots[snapshots.length - 1] === serialized) {
            return
        }
        snapshots.push(serialized)
        if (snapshots.length > MAX_TRACKED_LOCAL_SNAPSHOTS) {
            snapshots.splice(0, snapshots.length - MAX_TRACKED_LOCAL_SNAPSHOTS)
        }
    }, [])

    const commitDocument = useCallback(
        (nextDocument: NotebookDocument, options: CommitDocumentOptions = {}): void => {
            const editableDocument = ensureEditableNotebookDocument(nextDocument)
            const previousDocument = documentRef.current
            if (options.addToHistory ?? true) {
                pushHistoryEntry(previousDocument, editableDocument, options.historyOperations)
            }
            // Rendered remote carets ride along with the text they sit in.
            mapRemoteCaretAnchors(previousDocument, editableDocument, options.remoteMergeVersion)

            const serialized = serializeMarkdownNotebook(editableDocument)
            logDebugEntry('commit', {
                addToHistory: options.addToHistory ?? true,
                ...(options.remoteMergeVersion !== undefined ? { remoteMergeVersion: options.remoteMergeVersion } : {}),
                markdown: serialized,
            })
            documentRef.current = editableDocument
            lastSerializedValueRef.current = serialized
            trackLocalSnapshot(serialized)
            setDebugMarkdown(serialized)
            setDocument(editableDocument)
            onChange?.(serialized)
        },
        [onChange, pushHistoryEntry, mapRemoteCaretAnchors, logDebugEntry, trackLocalSnapshot]
    )

    const applyRemoteValue = useCallback(
        (nextRemoteValue: string): void => {
            const snapshotIndex =
                nextRemoteValue === lastSerializedValueRef.current
                    ? localSnapshotsRef.current.length - 1
                    : localSnapshotsRef.current.indexOf(nextRemoteValue)
            if (snapshotIndex !== -1) {
                // The remote state matches a recent local serialization: it's the echo of our own
                // save, so everything in it is already contained in the local state. Merging it
                // would re-apply insertions the local text has since built on, duplicating them —
                // only the merge base advances. Undo history must survive autosaves too.
                logDebugEntry('remote-echo', { behind: nextRemoteValue !== lastSerializedValueRef.current })
                lastRemoteValueRef.current = nextRemoteValue
                lastBaseValueRef.current = nextRemoteValue
                // Older snapshots can't echo after a newer one: saves are acknowledged in order.
                localSnapshotsRef.current.splice(0, snapshotIndex)
                return
            }

            const mergeResult = mergeNotebookMarkdownChanges({
                baseMarkdown: lastBaseValueRef.current,
                localMarkdown: lastSerializedValueRef.current,
                remoteMarkdown: nextRemoteValue,
            })
            logDebugEntry('remote-merge', {
                baseMarkdown: lastBaseValueRef.current,
                localMarkdown: lastSerializedValueRef.current,
                remoteMarkdown: nextRemoteValue,
                conflicts: mergeResult.conflicts,
            })
            const previousDocument = documentRef.current
            const reconciledDocument = ensureEditableNotebookDocument(
                reconcileNotebookDocuments(previousDocument, mergeResult.document).document
            )
            const restoreSelectionRequest = notebookRef.current
                ? getCollapsedSelectionRestoreRequest(window.getSelection(), notebookRef.current)
                : null
            lastRemoteValueRef.current = nextRemoteValue
            // The merge result still contains unsaved local changes, so the server state — not the
            // merge result — is the common ancestor for the next merge.
            lastBaseValueRef.current = nextRemoteValue
            // Remote edits rebase the undo stack over the merged-in operations, so CMD+Z keeps
            // reverting only this user's changes — never a collaborator's.
            rebaseHistoryThroughDocumentChange(previousDocument, reconciledDocument)
            if (restoreSelectionRequest) {
                // Map the caret through the merged-in remote changes so it stays at the same
                // place in the text — a collaborator typing at the start of this line must
                // push the caret along with the text, not leave it at a stale offset.
                const mappedRequest = mapRestoreSelectionThroughDocumentChange(
                    restoreSelectionRequest,
                    previousDocument,
                    reconciledDocument
                )
                restoreSelectionRef.current = mappedRequest
                // Re-publish the corrected caret right away, so collaborators see this
                // client's caret at its mapped position instead of the stale offset.
                if (mappedRequest && 'nodeId' in mappedRequest) {
                    const nodeIndex = reconciledDocument.nodes.findIndex((node) => node.id === mappedRequest.nodeId)
                    const node = reconciledDocument.nodes[nodeIndex]
                    if (nodeIndex !== -1) {
                        let listItemIndex = mappedRequest.listItemIndex
                        if (node?.type === 'list' && mappedRequest.listItemId !== undefined) {
                            const mappedItemIndex = node.items.findIndex((item) => item.id === mappedRequest.listItemId)
                            if (mappedItemIndex !== -1) {
                                listItemIndex = mappedItemIndex
                            }
                        }
                        onCaretChange?.(
                            mappedRequest.tableCell !== undefined
                                ? { nodeIndex }
                                : { nodeIndex, offset: mappedRequest.start, listItemIndex }
                        )
                    }
                }
            }
            commitDocument(reconciledDocument, {
                addToHistory: false,
                remoteMergeVersion: remoteVersionRef.current,
            })

            if (mergeResult.conflicts.length) {
                onConflict?.(mergeResult.conflicts)
            }
        },
        [commitDocument, onConflict, onCaretChange, rebaseHistoryThroughDocumentChange, logDebugEntry]
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

    // Anchor incoming caret pings against the current document. Declared after the
    // remoteValue effect on purpose: when a save event delivers content and the author's
    // piggybacked caret together, the merge applies first and the fresh ping re-anchors
    // against the post-merge document. Heartbeats re-delivering an unchanged ping keep
    // the locally remapped position instead of resetting to the stale offset.
    useEffect(() => {
        const previousAnchors = remoteCaretAnchorsRef.current
        const nextAnchors: Record<string, RemoteCaretAnchor> = {}
        for (const caret of remoteCarets ?? []) {
            const existingAnchor = previousAnchors[caret.clientId]
            if (existingAnchor && JSON.stringify(existingAnchor.source) === JSON.stringify(caret.position)) {
                nextAnchors[caret.clientId] = {
                    caret,
                    source: existingAnchor.source,
                    position: existingAnchor.position,
                }
            } else {
                nextAnchors[caret.clientId] = { caret, source: caret.position, position: caret.position }
            }
        }
        remoteCaretAnchorsRef.current = nextAnchors
        setAdjustedRemoteCarets(
            remoteCarets?.length
                ? Object.values(nextAnchors).map((anchor) => ({ ...anchor.caret, position: anchor.position }))
                : remoteCarets
        )
    }, [remoteCarets])

    // The AI prompt keeps the insert menu open while a question is composed, but the question
    // lives in a real Prompt node — that's content, not transient UI, so it must keep syncing
    // to collaborators instead of pausing autosave like the slash menu does.
    const isInsertMenuInteractionActive = !!insertMenu && insertMenu.mode !== 'ai'
    const isTransientInteractionActive = mode === 'edit' && (isInsertMenuInteractionActive || !!floatingToolbar)

    useEffect(() => {
        onInteractionStateChange?.(isTransientInteractionActive)
        return () => {
            if (isTransientInteractionActive) {
                onInteractionStateChange?.(false)
            }
        }
    }, [isTransientInteractionActive, onInteractionStateChange])

    const applyHistoryEntrySelection = useCallback(
        (entry: NotebookHistoryEntry, nextDocument: NotebookDocument): void => {
            const selection = entry.selection
            const entrySelection =
                selection && 'nodeId' in selection && nextDocument.nodes.some((node) => node.id === selection.nodeId)
                    ? selection
                    : null
            restoreSelectionRef.current = entrySelection ?? getHistoryRestoreSelection(nextDocument)
        },
        []
    )

    const undoHistory = useCallback((): boolean => {
        const entry = historyRef.current.undo[historyRef.current.undo.length - 1]
        if (!entry) {
            return false
        }

        const result = applyNotebookOperations(documentRef.current, entry.ops)
        if (!result) {
            // The entry no longer fits the document (a conflicting remote edit slipped past
            // the rebase): drop the stale stack rather than apply garbage.
            historyRef.current = { ...historyRef.current, undo: [] }
            return false
        }

        historyRef.current = {
            undo: historyRef.current.undo.slice(0, -1),
            redo: [
                ...historyRef.current.redo.slice(-(MAX_UNDO_HISTORY_ENTRIES - 1)),
                { ops: result.inverted, selection: captureHistorySelection(), editedAt: 0, coalesceNodeId: null },
            ],
        }
        applyHistoryEntrySelection(entry, result.document)
        commitDocument(result.document, { addToHistory: false })
        return true
    }, [applyHistoryEntrySelection, captureHistorySelection, commitDocument])

    const redoHistory = useCallback((): boolean => {
        const entry = historyRef.current.redo[historyRef.current.redo.length - 1]
        if (!entry) {
            return false
        }

        const result = applyNotebookOperations(documentRef.current, entry.ops)
        if (!result) {
            historyRef.current = { ...historyRef.current, redo: [] }
            return false
        }

        historyRef.current = {
            undo: [
                ...historyRef.current.undo.slice(-(MAX_UNDO_HISTORY_ENTRIES - 1)),
                { ops: result.inverted, selection: captureHistorySelection(), editedAt: 0, coalesceNodeId: null },
            ],
            redo: historyRef.current.redo.slice(0, -1),
        }
        applyHistoryEntrySelection(entry, result.document)
        commitDocument(result.document, { addToHistory: false })
        return true
    }, [applyHistoryEntrySelection, captureHistorySelection, commitDocument])

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

            if (selectedEntries.some((entry) => aiWritingNodeIndexSet.has(entry.index))) {
                return true
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
            const survivingIds = new Set(nextNodes.map((node) => node.id))
            const removedRefIds = new Set(
                selectedEntries
                    .filter((entry) => !survivingIds.has(entry.node.id))
                    .map((entry) => getDiscussionCommentRefId(entry.node))
                    .filter((refId): refId is string => !!refId)
            )
            commitDocument({
                ...currentDocument,
                nodes: stripNotebookRefMarksFromNodes(nextNodes, removedRefIds),
            })
            return true
        },
        [aiWritingNodeIndexSet, commitDocument]
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
            // A new item split off a task starts as an unchecked task
            checked: item.checked !== undefined ? false : undefined,
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

    // A ranged selection that reaches a list item's edge (e.g. the whole item selected up to
    // the next item's start) must be deleted through the model: the browser's native delete
    // merges `<li>` elements in place, and React then crashes on its next commit because the
    // list structure it manages no longer matches the DOM (removeChild NotFoundError).
    const deleteListItemRangeAtCurrentSelection = useCallback(
        (replacementText: string = '', claimSingleItemRange: boolean = false): boolean => {
            const notebookElement = notebookRef.current
            const selection = window.getSelection()
            if (!notebookElement || !selection || selection.rangeCount === 0 || selection.isCollapsed) {
                return false
            }

            const element = getSelectedInlineEditableElementOfType(
                notebookElement,
                'MarkdownNotebook__list-item-content'
            )
            const nodeId = element?.dataset.markdownNotebookNodeId
            if (!element || !nodeId) {
                return false
            }

            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            const node = nodes.find((currentNode) => currentNode.id === nodeId)
            if (!node || node.type !== 'list') {
                return false
            }

            const range = selection.getRangeAt(0)
            const listBlockElement = blockRefs.current[node.id]
            if (
                !listBlockElement ||
                !listBlockElement.contains(range.startContainer) ||
                !listBlockElement.contains(range.endContainer)
            ) {
                return false
            }

            // A range confined to a single item's content element is safe to leave to the
            // browser: only that item's manually synced innerHTML changes. Cut still claims it,
            // because cut prevents the browser default that would otherwise delete the text.
            const startElement = getClosestEditableBlockElement(getElementForNode(range.startContainer))
            const endElement = getClosestEditableBlockElement(getElementForNode(range.endContainer))
            if (!claimSingleItemRange && startElement === element && endElement === element) {
                return false
            }

            const itemRanges = node.items.flatMap((_, itemIndex) => {
                const itemElement = listItemRefs.current[getListItemRefKey(node.id, itemIndex)]
                const itemRange = itemElement ? getSelectionRange(itemElement, node.id) : null
                if (!itemRange) {
                    return []
                }
                return [
                    {
                        itemIndex,
                        start: Math.min(itemRange.start, itemRange.end),
                        end: Math.max(itemRange.start, itemRange.end),
                    },
                ]
            })

            // A zero-length range at the selection's edge is a boundary touch that selects
            // nothing in that item.
            while (itemRanges.length > 1 && itemRanges[0].start === itemRanges[0].end) {
                itemRanges.shift()
            }
            while (
                itemRanges.length > 1 &&
                itemRanges[itemRanges.length - 1].start === itemRanges[itemRanges.length - 1].end
            ) {
                itemRanges.pop()
            }
            const firstRange = itemRanges[0]
            const lastRange = itemRanges[itemRanges.length - 1]
            if (!firstRange || !lastRange) {
                return false
            }

            const deletion = deleteListItemSelectionRange(
                node.items,
                {
                    firstItemIndex: firstRange.itemIndex,
                    firstStart: firstRange.start,
                    lastItemIndex: lastRange.itemIndex,
                    lastEnd: lastRange.end,
                },
                replacementText
            )
            if (!deletion) {
                return false
            }

            restoreSelectionRef.current = {
                nodeId: node.id,
                listItemIndex: deletion.caretItemIndex,
                listItemId: deletion.caretItemId,
                start: deletion.caretOffset,
                end: deletion.caretOffset,
            }
            commitDocument({
                ...currentDocument,
                nodes: nodes.map((currentNode) =>
                    currentNode.id === node.id ? { ...node, items: deletion.items } : currentNode
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

            if (direction === 'backward' && selectionStart === 0 && nodeIndex === 0) {
                restoreSelectionRef.current = { nodeId: node.id, start: 0, end: 0 }
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
                            ? {
                                  ...currentNode,
                                  // A quoted heading downgrades to quote text, staying in the quote
                                  type: currentNode.blockquote ? 'blockquote' : 'paragraph',
                                  level: undefined,
                                  blockquote: undefined,
                              }
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

    // Chrome's default insertParagraph inside the code <pre> appends <br> elements, which are
    // invisible to textContent and therefore never reach the document model. Insert a literal
    // newline through the model instead.
    const insertNewlineInCodeBlockAtCurrentSelection = useCallback((): boolean => {
        const element = getSelectedInlineEditableElementOfType(notebookRef.current, 'MarkdownNotebook__code-block')
        const nodeId = element?.dataset.markdownNotebookNodeId
        if (!element || !nodeId) {
            return false
        }

        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
        const node = nodes.find((currentNode) => currentNode.id === nodeId)
        if (!node || node.type !== 'code') {
            return false
        }

        const range = getSelectionRange(element, nodeId)
        const textLength = node.text.length
        const start = range ? Math.max(0, Math.min(Math.min(range.start, range.end), textLength)) : textLength
        const end = range ? Math.max(start, Math.min(Math.max(range.start, range.end), textLength)) : textLength
        const nextText = `${node.text.slice(0, start)}\n${node.text.slice(end)}`

        restoreSelectionRef.current = { nodeId, start: start + 1, end: start + 1 }
        commitDocument({
            ...currentDocument,
            nodes: nodes.map((currentNode) =>
                currentNode.id === nodeId && currentNode.type === 'code'
                    ? { ...currentNode, text: nextText }
                    : currentNode
            ),
        })
        return true
    }, [commitDocument])

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
                (nativeEvent.inputType === 'insertParagraph' || nativeEvent.inputType === 'insertLineBreak') &&
                insertNewlineInCodeBlockAtCurrentSelection()
            ) {
                event.preventDefault()
                event.stopPropagation()
                return
            }

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
                (deleteSelectedNotebookBlocks(nativeEvent.data) ||
                    deleteListItemRangeAtCurrentSelection(nativeEvent.data))
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
                (deleteListItemRangeAtCurrentSelection() ||
                    deleteListItemAtCurrentSelection(
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

            // A native edit whose range crosses inline-editable boundaries would restructure
            // React-managed DOM and crash the next React commit. If no handler above claimed
            // the edit, dropping it is the safe outcome.
            if (
                NATIVE_RANGE_EDIT_INPUT_TYPES.has(nativeEvent.inputType) &&
                inputEventCrossesInlineEditableBoundary(nativeEvent, notebookElement)
            ) {
                logDebugEntry('blocked-cross-boundary-edit', { inputType: nativeEvent.inputType })
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
        deleteListItemRangeAtCurrentSelection,
        deleteSelectedNotebookBlocks,
        deleteTextAtCurrentSelection,
        logDebugEntry,
        insertNewlineInCodeBlockAtCurrentSelection,
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
            let historyOperations: NotebookOperation[] | undefined
            const nextNodes = nodes.flatMap((node, index) => {
                if (didUpdate || node.id !== nodeId) {
                    return [node]
                }
                didUpdate = true
                const updatedNode = updater(cloneNotebookNode(node))
                historyOperations = getComponentNodeUpdateHistoryOperations(nodes, index, node, updatedNode)
                return updatedNode ? [updatedNode] : []
            })

            if (!didUpdate) {
                return
            }

            commitDocument(
                {
                    ...currentDocument,
                    nodes: nextNodes,
                },
                {
                    historyOperations,
                }
            )
        },
        [commitDocument]
    )

    const replaceNode = useCallback(
        (nodeId: string, nextNode: NotebookBlockNode): void => {
            updateNode(nodeId, () => nextNode)
        },
        [updateNode]
    )

    // Deleting a discussion comment also unwraps its `<ref>` highlight; deleting anything
    // else is a plain removal.
    const deleteNodeWithRefCleanup = useCallback(
        (nodeId: string): void => {
            commitDocument(removeNotebookNodesWithRefCleanup(documentRef.current, new Set([nodeId])))
        },
        [commitDocument]
    )

    const replaceNodeWithInsertedComponent = useCallback(
        (nodeId: string, nextNode: NotebookComponentBlockNode): void => {
            const definition = getMarkdownNotebookComponentDefinition(mergedRegistry, nextNode.tagName)
            const insertedPanels = getInsertedComponentPanelVisibility(nextNode)
            const insertedNode = withPersistedComponentPanelProps(nextNode, definition, insertedPanels)
            markNotebookNodeFreshlyInserted(nextNode.id)
            focusNodeRef.current = nextNode.id
            replaceNode(nodeId, insertedNode)
        },
        [mergedRegistry, replaceNode]
    )

    const insertMenuApi = useMemo<MarkdownNotebookInsertMenuApi>(
        () => ({
            insertComponent: (targetNodeId, tagName, props) =>
                replaceNodeWithInsertedComponent(targetNodeId, {
                    id: makeEmptyParagraph(`component-${tagName}`).id,
                    type: 'component',
                    tagName,
                    props,
                }),
        }),
        [replaceNodeWithInsertedComponent]
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
        (
            nodeId: string,
            options?: { source?: 'slash' | 'selection'; selectedMarkdown?: string; selectedRefId?: string }
        ): void => {
            onInteractionStateChange?.(true)
            const currentDocument = documentRef.current
            const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
            let didUpdate = false
            const nextNodes = nodes.flatMap((currentNode): NotebookBlockNode[] => {
                if (didUpdate || currentNode.id !== nodeId) {
                    return [currentNode]
                }
                didUpdate = true
                if (!isTextBlockNode(currentNode) && currentNode.type !== 'component') {
                    return [currentNode]
                }
                const promptProps: NotebookComponentProps = { question: '' }
                if (options?.source === 'selection') {
                    promptProps.source = 'selection'
                    promptProps.selectedMarkdown = options.selectedMarkdown ?? ''
                    if (options.selectedRefId) {
                        promptProps.ref = options.selectedRefId
                    }
                }
                return [
                    {
                        id: currentNode.id,
                        type: 'component',
                        tagName: 'Prompt',
                        props: promptProps,
                    },
                ]
            })
            if (didUpdate) {
                commitDocument({
                    ...currentDocument,
                    nodes: nextNodes,
                })
            } else {
                commitDocument({
                    ...currentDocument,
                    nodes: nextNodes,
                })
            }
            setInsertMenu({
                nodeId,
                query: '',
                selectedIndex: 0,
                mode: 'ai',
                source: options?.source ?? 'slash',
                selectedMarkdown: options?.selectedMarkdown,
                selectedRefId: options?.selectedRefId,
            })
        },
        [commitDocument, onInteractionStateChange]
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
    const aiWritingPlaceholderNodeIds = useMemo(() => getAIWritingPlaceholderNodeIds(document.nodes), [document.nodes])
    const focusAIPromptNodeId = useMemo(
        () => (focusAIPromptRequest === undefined ? null : getLatestEmptyAIPromptNodeId(document.nodes)),
        [document.nodes, focusAIPromptRequest]
    )
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
                onAskAI ? openAIPrompt : undefined,
                false,
                extraInsertCommands ? extraInsertCommands(insertMenuApi) : []
            ),
        [
            mergedRegistry,
            replaceNodeWithInsertedComponent,
            replaceNode,
            onAskAI,
            openAIPrompt,
            extraInsertCommands,
            insertMenuApi,
        ]
    )

    function getRenderedNodes(): NotebookBlockNode[] {
        if (document.nodes.length || mode === 'view') {
            return document.nodes
        }
        return [emptyNodeRef.current]
    }

    useEffect(() => {
        const componentNodeIds = new Set(
            document.nodes.flatMap((node): string[] => {
                if (node.type !== 'component') {
                    return []
                }
                return [node.id]
            })
        )
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
            const insertedPanels = getInsertedComponentPanelVisibility(node)
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
            // Non-text blocks (queries, dividers, comments…) never produce a text caret, so
            // fall back to the focused block — collaborators still see who is on it.
            onCaretChange?.(
                getMarkdownNotebookCaretPosition(window.getSelection(), notebookElement, documentRef.current.nodes) ??
                    getFocusedBlockCaretPosition(
                        window.document.activeElement,
                        notebookElement,
                        documentRef.current.nodes,
                        blockRefs.current
                    )
            )
        }

        const handleDocumentPointerStart = (event: MouseEvent | PointerEvent | TouchEvent): void => {
            if (event.target instanceof HTMLElement && event.target.closest('.MarkdownNotebook__format-toolbar')) {
                return
            }

            floatingToolbarPositionLockRef.current = null
        }

        window.document.addEventListener('selectionchange', handleDocumentSelectionChange)
        // Focusing a non-editable block (component shell, divider, comment) doesn't fire
        // selectionchange, so focus moves must also refresh the reported caret.
        window.document.addEventListener('focusin', handleDocumentSelectionChange)
        window.document.addEventListener('mousedown', handleDocumentPointerStart, true)
        window.document.addEventListener('pointerdown', handleDocumentPointerStart, true)
        window.document.addEventListener('touchstart', handleDocumentPointerStart, true)
        window.addEventListener('resize', handleDocumentSelectionChange)
        window.addEventListener('scroll', handleDocumentSelectionChange, true)

        return () => {
            window.document.removeEventListener('selectionchange', handleDocumentSelectionChange)
            window.document.removeEventListener('focusin', handleDocumentSelectionChange)
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
        onCaretChange,
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
            if (!deleteSelectedNotebookBlocks() && !deleteListItemRangeAtCurrentSelection('', true)) {
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

    // Pasted files insert after the block holding the caret (or the focused component); pastes
    // with no block context append to the end.
    const getPasteInsertBoundaryIndex = (target: HTMLElement): number => {
        const nodes = documentRef.current.nodes.length ? documentRef.current.nodes : [emptyNodeRef.current]
        const focusedComponentNode = getFocusedComponentNode(target, nodes, blockRefs.current)
        const nodeId = focusedComponentNode
            ? focusedComponentNode.id
            : target.closest<HTMLElement>('[data-markdown-notebook-node-id]')?.dataset.markdownNotebookNodeId
        const nodeIndex = nodeId ? nodes.findIndex((node) => node.id === nodeId) : -1
        return nodeIndex === -1 ? nodes.length : nodeIndex + 1
    }

    const handleNotebookPaste = (event: ReactClipboardEvent<HTMLDivElement>): void => {
        if (mode !== 'edit' || !(event.target instanceof HTMLElement) || isNativeEditableElement(event.target)) {
            return
        }

        // Pasted files (e.g. a screenshot) have no text representation the editor could insert —
        // hand them to the external converter, mirroring the file drop path.
        const clipboardFiles = event.clipboardData?.files
        if (
            convertExternalDataTransferToNodes &&
            clipboardFiles?.length &&
            !event.clipboardData.getData('text/plain')
        ) {
            const result = convertExternalDataTransferToNodes(event.clipboardData)
            if (result) {
                event.preventDefault()
                event.stopPropagation()
                const boundaryIndex = getPasteInsertBoundaryIndex(event.target)
                if (result instanceof Promise) {
                    void result.then((insertedNodes) => {
                        if (insertedNodes?.length) {
                            insertExternalNodesAtBoundary(insertedNodes, boundaryIndex)
                        }
                    })
                    return
                }
                insertExternalNodesAtBoundary(result, boundaryIndex)
                return
            }
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

    const handleDebugMarkdownChange = (nextMarkdown: string): void => {
        const nextDocument = parseMarkdownNotebook(nextMarkdown)
        const reconciledDocument = ensureEditableNotebookDocument(
            reconcileNotebookDocuments(documentRef.current, nextDocument).document
        )
        const serialized = serializeMarkdownNotebook(reconciledDocument)

        documentRef.current = reconciledDocument
        lastSerializedValueRef.current = serialized
        trackLocalSnapshot(serialized)
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

        // The quote button toggles quote membership: unquote only when the whole selection is already quoted.
        const selectedNodes = nodes.filter(
            (node) =>
                selectedTextNodeIds.has(node.id) || selectedCodeNodeIds.has(node.id) || selectedListNodeIds.has(node.id)
        )
        const shouldUnquote =
            style === 'blockquote' && selectedNodes.length > 0 && selectedNodes.every(isGroupedBlockquoteNode)

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
                    if (style === 'blockquote') {
                        return { ...node, blockquote: shouldUnquote ? undefined : true }
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
                    // A heading applied inside a quote keeps its quote membership
                    return {
                        ...node,
                        type: 'heading',
                        level: style,
                        blockquote: node.type === 'blockquote' || node.blockquote ? true : undefined,
                    }
                }
                if (style === 'blockquote') {
                    if (node.type === 'heading') {
                        // Quote membership toggles without touching the heading level
                        return { ...node, blockquote: shouldUnquote ? undefined : true }
                    }
                    if (shouldUnquote) {
                        return { ...node, type: 'paragraph', level: undefined, blockquote: undefined }
                    }
                    return { ...node, type: 'blockquote', level: undefined, blockquote: undefined }
                }
                if (style === 'paragraph' && node.type === 'heading' && node.blockquote) {
                    // Removing the heading style inside a quote downgrades to quote text, not plain text
                    return { ...node, type: 'blockquote', level: undefined, blockquote: undefined }
                }
                return { ...node, type: style, level: undefined, blockquote: undefined }
            }),
        })
    }

    const setCodeRefMark = (
        node: NotebookCodeBlockNode,
        range: NotebookTextSelectionRange,
        refId: string
    ): NotebookCodeBlockNode => ({
        ...node,
        refs: [
            ...(node.refs ?? []).filter((ref) => ref.id !== refId),
            { id: refId, start: range.start, end: Math.min(range.end, node.text.length) },
        ],
    })

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
        const textRangesByNodeId = new Map(floatingToolbar.textRanges.map((entry) => [entry.node.id, entry]))
        const codeRangesByNodeId = new Map(floatingToolbar.codeRanges.map((entry) => [entry.node.id, entry]))
        const listItemRangesByNodeId = new Map<string, FloatingToolbarListItemRange[]>()
        floatingToolbar.listItemRanges.forEach((entry) => {
            listItemRangesByNodeId.set(entry.node.id, [...(listItemRangesByNodeId.get(entry.node.id) ?? []), entry])
        })
        const refId =
            floatingToolbar.textRanges.length +
                floatingToolbar.listItemRanges.length +
                floatingToolbar.codeRanges.length >
            0
                ? createNotebookRefId()
                : undefined
        // Insert the prompt after the last selected block in document order.
        const selectedNodeIds = new Set(
            [
                ...floatingToolbar.textRanges.map(({ node }) => node.id),
                ...floatingToolbar.codeRanges.map(({ node }) => node.id),
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
                ...(refId ? { ref: refId } : {}),
            },
        }
        onInteractionStateChange?.(true)
        const nextNodes = nodes.flatMap((node, index): NotebookBlockNode[] => {
            let updatedNode = node
            const textRange = textRangesByNodeId.get(node.id)
            const codeRange = codeRangesByNodeId.get(node.id)
            const listItemRanges = listItemRangesByNodeId.get(node.id)
            if (refId && textRange && isTextBlockNode(node)) {
                updatedNode = { ...node, children: setInlineRefMark(node.children, textRange.range, refId) }
            } else if (refId && codeRange && node.type === 'code') {
                updatedNode = setCodeRefMark(node, codeRange.range, refId)
            } else if (refId && listItemRanges && node.type === 'list') {
                updatedNode = {
                    ...node,
                    items: node.items.map((item, itemIndex) => {
                        const itemRange = listItemRanges.find((entry) => entry.itemIndex === itemIndex)
                        return itemRange
                            ? { ...item, children: setInlineRefMark(item.children, itemRange.range, refId) }
                            : item
                    }),
                }
            }
            return index === targetNodeIndex ? [updatedNode, promptNode] : [updatedNode]
        })
        if (refId) {
            restoreSelectionRef.current = {
                textRanges: [
                    ...floatingToolbar.textRanges.map(({ range }) => range),
                    ...floatingToolbar.listItemRanges.map(({ itemIndex, range }) => ({
                        ...range,
                        listItemIndex: itemIndex,
                    })),
                ],
            }
        }
        commitDocument({
            ...currentDocument,
            nodes: nextNodes,
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
            selectedRefId: refId,
        })
    }

    // Comments need at least one anchorable range: an inline `<ref>` mark for text and list
    // selections, or a block-level `refs` anchor for selections inside code blocks.
    const canStartInlineCommentAtSelection = (): boolean => {
        if (!floatingToolbar) {
            return false
        }
        return (
            floatingToolbar.textRanges.length +
                floatingToolbar.listItemRanges.length +
                floatingToolbar.codeRanges.length >=
            1
        )
    }

    const startInlineCommentAtSelection = (): void => {
        if (!floatingToolbar || !canStartInlineCommentAtSelection()) {
            return
        }

        const textRangesByNodeId = new Map(floatingToolbar.textRanges.map((entry) => [entry.node.id, entry]))
        const codeRangesByNodeId = new Map(floatingToolbar.codeRanges.map((entry) => [entry.node.id, entry]))
        const listItemRangesByNodeId = new Map<string, FloatingToolbarListItemRange[]>()
        floatingToolbar.listItemRanges.forEach((entry) => {
            listItemRangesByNodeId.set(entry.node.id, [...(listItemRangesByNodeId.get(entry.node.id) ?? []), entry])
        })

        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
        const firstSelectedIndex = nodes.findIndex(
            (node) =>
                textRangesByNodeId.has(node.id) ||
                listItemRangesByNodeId.has(node.id) ||
                codeRangesByNodeId.has(node.id)
        )
        if (firstSelectedIndex === -1) {
            return
        }

        const refId = createNotebookRefId()
        // The thread sits above the first block it refers to, so its zero-height margin row
        // naturally aligns with the top of the highlighted content. The title row is the
        // one exception: the `# ` heading always stays first, so a title comment goes
        // right below it instead.
        const commentNode: NotebookComponentBlockNode = {
            id: makeEmptyParagraph(`comment-${nodes[firstSelectedIndex].id}`).id,
            type: 'component',
            tagName: 'Comment',
            props: { ref: refId, replies: [] },
        }
        const nextNodes = nodes.flatMap((node, index): NotebookBlockNode[] => {
            let updatedNode = node
            const textRange = textRangesByNodeId.get(node.id)
            const codeRange = codeRangesByNodeId.get(node.id)
            const listItemRanges = listItemRangesByNodeId.get(node.id)
            if (textRange && isTextBlockNode(node)) {
                updatedNode = { ...node, children: setInlineRefMark(node.children, textRange.range, refId) }
            } else if (codeRange && node.type === 'code') {
                updatedNode = setCodeRefMark(node, codeRange.range, refId)
            } else if (listItemRanges && node.type === 'list') {
                updatedNode = {
                    ...node,
                    items: node.items.map((item, itemIndex) => {
                        const itemRange = listItemRanges.find((entry) => entry.itemIndex === itemIndex)
                        return itemRange
                            ? { ...item, children: setInlineRefMark(item.children, itemRange.range, refId) }
                            : item
                    }),
                }
            }
            if (index !== firstSelectedIndex) {
                return [updatedNode]
            }
            return index === 0 ? [updatedNode, commentNode] : [commentNode, updatedNode]
        })

        markNotebookNodeFreshlyInserted(commentNode.id)
        floatingToolbarPositionLockRef.current = null
        setFloatingToolbar(null)
        window.getSelection()?.removeAllRanges()
        commitDocument({ ...currentDocument, nodes: nextNodes })
    }

    // Clicking a `<ref>` highlight scrolls its comment thread into view and flashes it.
    const focusDiscussionCommentForRef = (refId: string): void => {
        const commentNode = documentRef.current.nodes.find((node) => getDiscussionCommentRefId(node) === refId)
        const element = commentNode ? blockRefs.current[commentNode.id] : null
        if (!element) {
            return
        }

        scrollNotebookElementIntoView(element)
        element.classList.add('MarkdownNotebook__component-shell--comment-flash')
        window.setTimeout(() => element.classList.remove('MarkdownNotebook__component-shell--comment-flash'), 1600)
    }

    const focusDiscussionCommentComposer = (nodeId: string): void => {
        window.setTimeout(() => {
            const element = blockRefs.current[nodeId]
            const textarea = element?.querySelector(
                '[data-attr="notebook-discussion-comment-input"] textarea, textarea[data-attr="notebook-discussion-comment-input"]'
            )
            if (textarea instanceof HTMLTextAreaElement) {
                textarea.focus()
                textarea.setSelectionRange(textarea.value.length, textarea.value.length)
                return
            }
            element?.focus()
        }, 0)
    }

    const handleCanvasClick = (event: ReactMouseEvent<HTMLDivElement>): void => {
        const refElement = event.target instanceof Element ? event.target.closest('[data-notebook-ref]') : null
        const refId = refElement?.getAttribute('data-notebook-ref')
        if (refId) {
            focusDiscussionCommentForRef(refId)
        }
    }

    // A block comment has no `<ref>` highlight: the thread anchors purely by sitting right
    // above the block it discusses (below it for the title row, which always stays first).
    const startBlockCommentForNode = (nodeId: string): void => {
        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
        const targetIndex = nodes.findIndex((node) => node.id === nodeId)
        if (targetIndex === -1) {
            return
        }

        const insertIndex = Math.max(targetIndex, 1)
        const existingCommentNode = nodes[insertIndex - 1]
        if (
            existingCommentNode &&
            isDiscussionCommentNode(existingCommentNode) &&
            !getDiscussionCommentRefId(existingCommentNode)
        ) {
            focusDiscussionCommentComposer(existingCommentNode.id)
            return
        }

        const commentNode: NotebookComponentBlockNode = {
            id: makeEmptyParagraph(`comment-${nodeId}`).id,
            type: 'component',
            tagName: 'Comment',
            props: { replies: [] },
        }
        markNotebookNodeFreshlyInserted(commentNode.id)
        commitDocument({
            ...currentDocument,
            nodes: [...nodes.slice(0, insertIndex), commentNode, ...nodes.slice(insertIndex)],
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

    const insertParagraphBelowTrailingCodeBlockAtCurrentSelection = useCallback((): boolean => {
        const element = getSelectedInlineEditableElementOfType(notebookRef.current, 'MarkdownNotebook__code-block')
        const nodeId = element?.dataset.markdownNotebookNodeId
        if (!element || !nodeId) {
            return false
        }

        const nodes = documentRef.current.nodes.length ? documentRef.current.nodes : [emptyNodeRef.current]
        const nodeIndex = nodes.findIndex((currentNode) => currentNode.id === nodeId)
        const node = nodes[nodeIndex]
        if (!node || node.type !== 'code' || nodeIndex !== nodes.length - 1) {
            return false
        }

        const range = getCollapsedSelectionRange(element, nodeId)
        if (!range || range.end < node.text.lastIndexOf('\n') + 1) {
            return false
        }

        insertEmptyParagraphAfterNode(nodeId)
        return true
    }, [insertEmptyParagraphAfterNode])

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
        []
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
            return updateNotebookCodeBlockText(currentNode, element.textContent ?? '')
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
        const shiftInlineMarkShortcuts: Partial<Record<string, NotebookInlineMark['type']>> = {
            x: 'strike',
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

        const inlineMarkType = event.shiftKey ? shiftInlineMarkShortcuts[key] : inlineMarkShortcuts[key]
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

    const clearBlockDragState = (): void => {
        blockDragNodeIdRef.current = null
        setDraggingNodeId(null)
        setDropBoundaryIndex(null)
    }

    const getDropBoundaryIndexFromPointer = (clientY: number): number => {
        let boundaryIndex = renderedNodes.length
        for (let index = 0; index < renderedNodes.length; index++) {
            const node = renderedNodes[index]
            // Margin comments render as zero-height rows anchored elsewhere — not drop positions.
            if (isDiscussionCommentNode(node)) {
                continue
            }

            const blockElement = blockRefs.current[node.id]
            const rowElement = blockElement?.closest('.MarkdownNotebook__row') ?? blockElement
            if (!rowElement) {
                continue
            }

            const rect = rowElement.getBoundingClientRect()
            if (clientY < rect.top + rect.height / 2) {
                boundaryIndex = index
                break
            }
        }
        // The title block always stays first: nothing may drop before it.
        return Math.max(1, Math.min(boundaryIndex, renderedNodes.length))
    }

    const moveBlockToBoundary = (nodeId: string, boundaryIndex: number): void => {
        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
        const fromIndex = nodes.findIndex((node) => node.id === nodeId)
        if (fromIndex <= 0) {
            return
        }

        const clampedBoundaryIndex = Math.max(1, Math.min(boundaryIndex, nodes.length))
        if (clampedBoundaryIndex === fromIndex || clampedBoundaryIndex === fromIndex + 1) {
            return
        }

        const nextNodes = [...nodes]
        const [movedNode] = nextNodes.splice(fromIndex, 1)
        nextNodes.splice(
            clampedBoundaryIndex > fromIndex ? clampedBoundaryIndex - 1 : clampedBoundaryIndex,
            0,
            movedNode
        )
        commitDocument({ ...currentDocument, nodes: nextNodes })
    }

    const handleBlockDragStart = (event: ReactDragEvent<HTMLDivElement>, nodeId: string): void => {
        event.stopPropagation()
        blockDragNodeIdRef.current = nodeId
        setDraggingNodeId(nodeId)
        if (event.dataTransfer) {
            event.dataTransfer.setData('text/plain', nodeId)
            event.dataTransfer.effectAllowed = 'move'
            const rowElement = blockRefs.current[nodeId]?.closest('.MarkdownNotebook__row')
            if (rowElement instanceof HTMLElement && typeof event.dataTransfer.setDragImage === 'function') {
                event.dataTransfer.setDragImage(rowElement, 0, rowElement.getBoundingClientRect().height / 2)
            }
        }
    }

    const handleBlockDragEnd = (): void => {
        clearBlockDragState()
    }

    // Drags carrying an app resource (custom `node` type), files, or a URL are treated as external
    // inserts. URL drags only count when the drag started outside this editor — dragging a link
    // (or linked text) within the notebook stays on the browser's native contentEditable handling.
    const isExternalNotebookDrag = (dataTransfer: DataTransfer | null): boolean =>
        !!dataTransfer &&
        (dataTransfer.types.includes('node') ||
            dataTransfer.types.includes('Files') ||
            (dataTransfer.types.includes('text/uri-list') && !canvasDragOriginRef.current))

    const acceptsExternalDrag = (event: ReactDragEvent<HTMLDivElement>): boolean =>
        mode === 'edit' && !!convertExternalDataTransferToNodes && isExternalNotebookDrag(event.dataTransfer)

    const clearExternalDragState = (): void => {
        setIsExternalDragOver(false)
        setDropBoundaryIndex(null)
    }

    const insertExternalNodesAtBoundary = (insertedNodes: NotebookBlockNode[], boundaryIndex: number): void => {
        if (!insertedNodes.length) {
            return
        }

        const currentDocument = documentRef.current
        const nodes = currentDocument.nodes.length ? currentDocument.nodes : [emptyNodeRef.current]
        // The title block always stays first: nothing may drop before it.
        const clampedBoundaryIndex = Math.max(1, Math.min(boundaryIndex, nodes.length))
        insertedNodes.forEach((node) => markNotebookNodeFreshlyInserted(node.id))
        commitDocument({
            ...currentDocument,
            nodes: [...nodes.slice(0, clampedBoundaryIndex), ...insertedNodes, ...nodes.slice(clampedBoundaryIndex)],
        })
    }

    const handleCanvasDragOver = (event: ReactDragEvent<HTMLDivElement>): void => {
        if (!blockDragNodeIdRef.current) {
            if (!acceptsExternalDrag(event)) {
                return
            }

            event.preventDefault()
            if (event.dataTransfer) {
                event.dataTransfer.dropEffect = 'copy'
            }
            setIsExternalDragOver(true)
            setDropBoundaryIndex(getDropBoundaryIndexFromPointer(event.clientY))
            return
        }

        // preventDefault both allows dropping and suppresses the contentEditable native text drag.
        event.preventDefault()
        if (event.dataTransfer) {
            event.dataTransfer.dropEffect = 'move'
        }
        setDropBoundaryIndex(getDropBoundaryIndexFromPointer(event.clientY))
    }

    const handleCanvasDrop = (event: ReactDragEvent<HTMLDivElement>): void => {
        const nodeId = blockDragNodeIdRef.current
        if (!nodeId) {
            if (!acceptsExternalDrag(event) || !event.dataTransfer) {
                return
            }

            event.preventDefault()
            const boundaryIndex = getDropBoundaryIndexFromPointer(event.clientY)
            clearExternalDragState()
            const result = convertExternalDataTransferToNodes?.(event.dataTransfer)
            if (!result) {
                return
            }
            if (result instanceof Promise) {
                void result.then((insertedNodes) => {
                    if (insertedNodes?.length) {
                        insertExternalNodesAtBoundary(insertedNodes, boundaryIndex)
                    }
                })
                return
            }
            insertExternalNodesAtBoundary(result, boundaryIndex)
            return
        }

        event.preventDefault()
        const boundaryIndex = getDropBoundaryIndexFromPointer(event.clientY)
        clearBlockDragState()
        moveBlockToBoundary(nodeId, boundaryIndex)
    }

    const handleCanvasDragLeave = (event: ReactDragEvent<HTMLDivElement>): void => {
        if (!blockDragNodeIdRef.current && !isExternalDragOver) {
            return
        }

        const nextTarget = event.relatedTarget
        if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) {
            return
        }
        setIsExternalDragOver(false)
        setDropBoundaryIndex(null)
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
                return updateNotebookCodeBlockText(currentNode, inlineEditableElement.textContent ?? '')
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

            const listNode = nodes.find((node) => node.id === nodeId)
            let taskShortcut: ReturnType<typeof getTaskItemShortcut> = null
            if (listNode?.type === 'list') {
                const item = listNode.items[getListItemIndex(listNode.items, itemIndex, itemId)]
                if (item && item.checked === undefined && !(item.ordered ?? listNode.ordered)) {
                    taskShortcut = getTaskItemShortcut(nextChildren)
                }
            }
            if (taskShortcut) {
                const caretOffset = Math.max(
                    0,
                    (getCollapsedSelectionRange(inlineEditableElement, nodeId)?.start ?? taskShortcut.markerLength) -
                        taskShortcut.markerLength
                )
                restoreSelectionRef.current = {
                    nodeId,
                    listItemIndex: itemIndex,
                    listItemId: itemId,
                    start: caretOffset,
                    end: caretOffset,
                }
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
                        index === targetItemIndex
                            ? taskShortcut
                                ? { ...item, checked: taskShortcut.checked, children: taskShortcut.children }
                                : { ...item, children: nextChildren }
                            : item
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
        if (selectedCommand.disabled) {
            return true
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
        if (isAIPromptSubmitDisabled) {
            return false
        }

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

        let responseNodeIndex = -1
        const nodesWithResponse = nodes.map((currentNode, index): NotebookBlockNode => {
            if (currentNode.id !== nodeId || !isPromptComponentNode(currentNode)) {
                return currentNode
            }
            responseNodeIndex = index
            return {
                id: currentNode.id,
                type: 'paragraph',
                children: plainTextToInlineNodes(NOTEBOOK_AI_WRITING_PLACEHOLDER),
            }
        })
        if (responseNodeIndex === -1) {
            console.error('Prompt node not found for AI submission')
            return false
        }

        const conversationId = createAIConversationId()
        const nextDocument: NotebookDocument = { ...currentDocument, nodes: nodesWithResponse }
        commitDocument(nextDocument)
        clearInsertMenu()
        const markdownWithResponse = serializeMarkdownNotebook(nextDocument)
        const responseMarker = NOTEBOOK_AI_WRITING_PLACEHOLDER
        const source = activeAIPromptMenu?.source ?? getPromptSource(currentPromptNode?.props.source)
        const selectedMarkdown =
            activeAIPromptMenu?.selectedMarkdown ?? getNotebookStringProp(currentPromptNode?.props.selectedMarkdown)
        const selectedRefId = activeAIPromptMenu?.selectedRefId ?? getNotebookStringProp(currentPromptNode?.props.ref)
        onAskAI({
            conversationId,
            query:
                source === 'selection' && selectedMarkdown
                    ? getAskAISelectionQuery(
                          selectedMarkdown,
                          query,
                          responseMarker,
                          selectedRefId,
                          markdownWithResponse
                      )
                    : getAskAIInlineNotebookQuery(query, responseMarker, markdownWithResponse),
            source,
            responseNodeId: nodeId,
            responseNodeIndex,
            responseMarker,
            markdown: markdownWithResponse,
            markdownWithResponse,
            selectedMarkdown,
            selectedRefId,
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

        if (
            mode === 'edit' &&
            event.key === 'F10' &&
            event.altKey &&
            !event.metaKey &&
            !event.ctrlKey &&
            focusFormattingToolbar()
        ) {
            event.preventDefault()
            event.stopPropagation()
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
            (deleteListItemRangeAtCurrentSelection() ||
                deleteListItemAtCurrentSelection(event.key === 'Backspace' ? 'backward' : 'forward') ||
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
            mode === 'edit' &&
            event.key === 'ArrowDown' &&
            !event.shiftKey &&
            !event.altKey &&
            !event.metaKey &&
            !event.ctrlKey &&
            insertParagraphBelowTrailingCodeBlockAtCurrentSelection()
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

    // Alt+F10 moves keyboard focus into the floating toolbar (the standard editor-toolbar
    // shortcut); Escape in the toolbar hands focus back without collapsing the selection.
    const focusFormattingToolbar = (): boolean => {
        if (!floatingToolbar) {
            return false
        }

        lockFloatingToolbarPosition()
        const button = mainRef.current?.querySelector<HTMLButtonElement>(
            '.MarkdownNotebook__format-toolbar button:not([disabled])'
        )
        if (!button) {
            return false
        }

        button.focus()
        return true
    }

    const returnFocusFromFormattingToolbar = (): void => {
        canvasRef.current?.focus()
    }

    const renderedNodeGroups = getMarkdownNotebookVisualGroups(
        renderedNodes,
        insertMenu?.detached ? insertMenu.nodeId : undefined
    )

    // The insert menu never takes focus (typing keeps filtering), so the canvas points at the
    // selected option via aria-activedescendant.
    const activeInsertMenuCommands =
        insertMenu && (insertMenu.mode ?? 'tools') === 'tools'
            ? getFilteredInsertCommands(insertCommands, insertMenu.query)
            : null
    const activeInsertMenuCommand =
        activeInsertMenuCommands?.[
            getClampedInsertMenuSelectedIndex(insertMenu?.selectedIndex ?? 0, activeInsertMenuCommands.length)
        ]
    const activeInsertMenuOptionDomId = activeInsertMenuCommand
        ? getInsertMenuOptionDomId(insertMenuDomId, activeInsertMenuCommand.key)
        : undefined

    const dropIndicatorTarget: { index: number; position: 'before' | 'after' } | null =
        (draggingNodeId !== null || isExternalDragOver) && dropBoundaryIndex !== null
            ? dropBoundaryIndex < renderedNodes.length
                ? { index: dropBoundaryIndex, position: 'before' }
                : renderedNodes.length
                  ? { index: renderedNodes.length - 1, position: 'after' }
                  : null
            : null

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

    const renderDebugToolbar = (): JSX.Element | null => {
        if (!showDebug) {
            return null
        }

        return (
            <div className="MarkdownNotebook__debug-toolbar" contentEditable={false}>
                <LemonButton
                    size="small"
                    icon={<IconCode />}
                    active={isDebugOpen}
                    tooltip="Edit markdown source"
                    aria-label="Edit markdown source"
                    aria-controls={debugDrawerId}
                    aria-expanded={isDebugOpen}
                    onClick={() => setDebugOpen((isOpen) => !isOpen)}
                />
            </div>
        )
    }

    const renderNotebookRow = (node: NotebookBlockNode, index: number): JSX.Element => {
        const isTitleRow = index === 0
        const isAIWritingNode = aiWritingNodeIndexSet.has(index)
        const nodeMode = isAIWritingNode ? 'view' : mode
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

        const isDraggableRow = mode === 'edit' && !isTitleRow && !isDiscussionCommentNode(node) && !isAIWritingNode

        return (
            <div
                className={clsx(
                    'MarkdownNotebook__row',
                    isInsertMenuOpen && 'MarkdownNotebook__row--insert-menu-open',
                    isAIPromptOpen && 'MarkdownNotebook__row--ai-prompt',
                    isAIWritingNode && 'MarkdownNotebook__row--ai-writing',
                    isDiscussionCommentNode(node) && 'MarkdownNotebook__row--margin-comment',
                    draggingNodeId === node.id && 'MarkdownNotebook__row--dragging'
                )}
                onMouseEnter={(event) => updateActiveBoundaryFromRow(event, index)}
                onMouseMove={(event) => updateActiveBoundaryFromRow(event, index)}
                onFocusCapture={() => handleRowFocus(index)}
                onBlurCapture={(event) => handleRowBlur(event, index)}
            >
                {isDraggableRow ? (
                    <div
                        className="MarkdownNotebook__drag-handle"
                        contentEditable={false}
                        draggable
                        role="button"
                        aria-label="Drag to move block"
                        data-attr="markdown-notebook-drag-handle"
                        onMouseDown={(event) => event.stopPropagation()}
                        onClick={(event) => {
                            event.preventDefault()
                            event.stopPropagation()
                        }}
                        onDragStart={(event) => handleBlockDragStart(event, node.id)}
                        onDragEnd={handleBlockDragEnd}
                    >
                        <IconDrag />
                    </div>
                ) : null}
                {isDraggableRow ? (
                    <div
                        className="MarkdownNotebook__block-comment-button"
                        contentEditable={false}
                        role="button"
                        aria-label="Comment on block"
                        title="Comment"
                        data-attr="markdown-notebook-block-comment-button"
                        onMouseDown={(event) => event.stopPropagation()}
                        onClick={(event) => {
                            event.preventDefault()
                            event.stopPropagation()
                            startBlockCommentForNode(node.id)
                        }}
                    >
                        <IconComment />
                    </div>
                ) : null}
                {dropIndicatorTarget?.index === index ? (
                    <div
                        className={clsx(
                            'MarkdownNotebook__drop-indicator',
                            dropIndicatorTarget.position === 'after' && 'MarkdownNotebook__drop-indicator--after'
                        )}
                        contentEditable={false}
                    />
                ) : null}
                {renderNode({
                    node,
                    nodeIndex: index,
                    mode: nodeMode,
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
                    toggleComponentPanel: (panel) => {
                        const nextPanels = {
                            ...nodeComponentPanels,
                            [panel]: !nodeComponentPanels[panel],
                        }

                        if (!persistComponentPanelVisibility) {
                            setLocalComponentPanels(node.id, nextPanels)
                            return
                        }

                        updateNode(node.id, (currentNode) => {
                            if (currentNode.type !== 'component') {
                                return currentNode
                            }

                            return withPersistedComponentPanelProps(currentNode, componentDefinition, nextPanels)
                        })
                    },
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
                    deleteNode: () => deleteNodeWithRefCleanup(node.id),
                    deleteNodeAndFocusAdjacent: () => {
                        requestFocusAfterRemovingNode(node.id)
                        deleteNodeWithRefCleanup(node.id)
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
                    showInlineInsertMenuButton: mode === 'edit' && !isAIWritingNode && shouldShowInlineInsertMenuButton,
                    isInlineInsertMenuButtonVisible: activeRowIndex === index || isToolInsertMenuOpen || isAIPromptOpen,
                    isInsertMenuOpen,
                    insertMenuMode,
                    hasInvalidInsertMenuQuery,
                    isAIWriting: isAIWritingNode,
                    isAIWritingPlaceholder: aiWritingPlaceholderNodeIds.has(node.id),
                    aiPromptFocusRequest:
                        focusAIPromptNodeId === node.id && focusAIPromptRequest !== undefined
                            ? focusAIPromptRequest
                            : undefined,
                    isAIPromptSubmitDisabled,
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
                        id={insertMenuDomId}
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

    const firstTextGroupKey = renderedNodeGroups.find((group) => group.type === 'text')?.key

    return (
        <div
            className={clsx(
                'MarkdownNotebook',
                isDebugOpen && 'MarkdownNotebook--debug-open',
                mode === 'edit' && 'MarkdownNotebook--edit',
                hasDiscussionComments &&
                    (fitsCommentGutter ? 'MarkdownNotebook--comments-margin' : 'MarkdownNotebook--comments-inline'),
                className
            )}
            data-attr={dataAttr}
            ref={notebookRef}
            onCopy={handleCopy}
            onCut={handleCut}
            onPaste={handleNotebookPaste}
            onKeyDownCapture={handleNotebookKeyDown}
        >
            <div className="MarkdownNotebook__debug-layout">
                <div className="MarkdownNotebook__main" ref={mainRef} onMouseDown={handleMainMouseDown}>
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
                        role={mode === 'edit' ? 'textbox' : undefined}
                        aria-multiline={mode === 'edit' ? true : undefined}
                        aria-label={mode === 'edit' ? 'Notebook editor' : undefined}
                        aria-controls={activeInsertMenuOptionDomId ? insertMenuDomId : undefined}
                        aria-expanded={activeInsertMenuOptionDomId ? true : undefined}
                        aria-activedescendant={activeInsertMenuOptionDomId}
                        onInput={handleRootEditableInput}
                        onKeyDown={handleRootEditableKeyDown}
                        onMouseLeave={handleCanvasMouseLeave}
                        onClick={handleCanvasClick}
                        onDragStartCapture={() => {
                            canvasDragOriginRef.current = true
                        }}
                        onDragEndCapture={() => {
                            canvasDragOriginRef.current = false
                        }}
                        onDragOver={handleCanvasDragOver}
                        onDrop={handleCanvasDrop}
                        onDragLeave={handleCanvasDragLeave}
                    >
                        {renderInsertBoundaryButton(0)}
                        {renderedNodeGroups.map((group) => {
                            if (group.type === 'text') {
                                const lastItem = group.items[group.items.length - 1]
                                const chunks: { surface: MarkdownNotebookTextSurface; items: typeof group.items }[] = []
                                for (const item of group.items) {
                                    const lastChunk = chunks[chunks.length - 1]
                                    // Code blocks never merge: each one is its own surface with its own line
                                    // numbers and copy button.
                                    if (lastChunk && lastChunk.surface === item.surface && item.surface !== 'code') {
                                        lastChunk.items.push(item)
                                    } else {
                                        chunks.push({ surface: item.surface, items: [item] })
                                    }
                                }

                                return (
                                    <Fragment key={group.key}>
                                        <div
                                            className={clsx(
                                                'MarkdownNotebook__text-group',
                                                group.key === firstTextGroupKey &&
                                                    showDebug &&
                                                    'MarkdownNotebook__text-group--with-debug-toolbar'
                                            )}
                                        >
                                            {group.key === firstTextGroupKey ? renderDebugToolbar() : null}
                                            {chunks.map((chunk) => {
                                                const chunkLastIndex = chunk.items[chunk.items.length - 1].index
                                                const rows = chunk.items.map(({ node, index }) => (
                                                    <Fragment key={node.id}>
                                                        {renderNotebookRow(node, index)}
                                                        {chunk.surface === 'text' && index < chunkLastIndex
                                                            ? renderInsertBoundaryButton(index + 1, {
                                                                  isGapClickable: false,
                                                              })
                                                            : null}
                                                    </Fragment>
                                                ))

                                                return (
                                                    <Fragment key={chunk.items[0].node.id}>
                                                        {chunk.surface === 'quote' ? (
                                                            <div className="MarkdownNotebook__blockquote-group">
                                                                {rows}
                                                            </div>
                                                        ) : chunk.surface === 'code' ? (
                                                            <div className="MarkdownNotebook__code-group">{rows}</div>
                                                        ) : (
                                                            rows
                                                        )}
                                                        {chunkLastIndex < lastItem.index
                                                            ? renderInsertBoundaryButton(chunkLastIndex + 1, {
                                                                  isGapClickable: false,
                                                              })
                                                            : null}
                                                    </Fragment>
                                                )
                                            })}
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
                    {adjustedRemoteCarets?.length ? (
                        <RemoteCaretOverlay
                            carets={adjustedRemoteCarets}
                            nodes={document.nodes}
                            blockRefs={blockRefs}
                            listItemRefs={listItemRefs}
                            containerRef={mainRef}
                        />
                    ) : null}
                    {floatingToolbar && mode === 'edit' ? (
                        <FormattingToolbar
                            selectedBlockStyle={getSelectedBlockStyle(
                                floatingToolbar.textRanges,
                                floatingToolbar.codeRanges,
                                floatingToolbar.listItemRanges
                            )}
                            selectedBlockQuoted={getSelectedBlocksQuoted(
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
                            isAskAIDisabled={false}
                            startInlineCommentAtSelection={
                                canStartInlineCommentAtSelection() ? startInlineCommentAtSelection : undefined
                            }
                            lockPosition={lockFloatingToolbarPosition}
                            returnFocusToEditor={returnFocusFromFormattingToolbar}
                        />
                    ) : null}
                </div>
                {showDebug && isDebugOpen ? (
                    <aside className="MarkdownNotebook__debug-drawer" id={debugDrawerId}>
                        <div className="MarkdownNotebook__debug-drawer-header">
                            <span>Markdown</span>
                            <div className="flex items-center gap-1">
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    status={isDebugLogging ? 'danger' : undefined}
                                    tooltip={
                                        isDebugLogging
                                            ? 'Stop recording and download the log'
                                            : 'Record keystrokes, mouse events, and document changes into a downloadable log'
                                    }
                                    onClick={isDebugLogging ? stopDebugLoggingAndDownload : startDebugLogging}
                                    data-attr="markdown-notebook-debug-log-toggle"
                                >
                                    {isDebugLogging ? 'Stop' : 'Log'}
                                </LemonButton>
                                <LemonButton size="xsmall" onClick={() => setDebugOpen(false)}>
                                    Close
                                </LemonButton>
                            </div>
                        </div>
                        <div className="MarkdownNotebook__debug-markdown" aria-label="Markdown debug output">
                            <Suspense
                                fallback={
                                    <div className="MarkdownNotebook__debug-markdown-loading">
                                        <Spinner />
                                    </div>
                                }
                            >
                                <LazyCodeEditor
                                    language="markdown"
                                    value={debugMarkdown}
                                    onChange={(nextMarkdown) => handleDebugMarkdownChange(nextMarkdown ?? '')}
                                    height="100%"
                                    options={{
                                        minimap: { enabled: false },
                                        wordWrap: 'on',
                                        lineNumbers: 'on',
                                        folding: false,
                                        scrollBeyondLastLine: false,
                                        automaticLayout: true,
                                        fontSize: 12,
                                    }}
                                />
                            </Suspense>
                        </div>
                    </aside>
                ) : null}
            </div>
        </div>
    )
}
