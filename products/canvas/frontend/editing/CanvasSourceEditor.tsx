import { useActions, useValues } from 'kea'
import { useEffect, useLayoutEffect, useRef } from 'react'

import { assertCanvasCapability } from '../host/canvasCapabilities'
import { CanvasDocumentBridge } from '../host/canvasDocumentBridge'
import { CanvasHostCallbacks, createCanvasHostMessageRouter } from '../host/canvasHostMessageRouter'
import {
    CanvasTheme,
    CanvasEditMessage,
    canvasEditMessageSchema,
    canvasToHostMessageSchema,
} from '../host/canvasProtocol'
import { CANVAS_ENTRY_PATH } from './blockLibrary/blockProject'
import { parseParamSchema } from './blockLibrary/params'
import type { SourceRange } from './blockLibrary/sourceEdits'
import { CanvasEditKey, canvasEditLogic } from './canvasEditLogic'
import { connectCanvasEditor, postToCanvasEditor } from './canvasEditorFrame'
import type { CanvasEditSelection } from './canvasSourceSnapshots'
import { SourceDropHit, activeSourceDrag, beginSourceDrag } from './sourceDrag'
import { SourceDragOverlay } from './SourceDragOverlay'

export interface CanvasSourceEditorProps extends CanvasHostCallbacks {
    /** The sandbox bootstrap document on the artifact origin. It carries the edit runtime. */
    documentUrl: string
    theme: CanvasTheme
    hasUserActivation: () => boolean
    onOpenExternal: (url: string) => void
}

/** The frame reports the param schema as the raw JSON the component declared. */
interface EditElementMessage extends Omit<CanvasEditSelection, 'params'> {
    params: string | null
}

function toSelection(element: EditElementMessage | null | undefined): CanvasEditSelection | null {
    return element ? { ...element, params: parseParamSchema(element.params) } : null
}

function isTypingTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) {
        return false
    }
    return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

/**
 * The canvas in edit mode: the head source runs in the sandbox with the edit runtime on, which
 * outlines the element under the pointer and reports selection, drags and text edits back here.
 * Every local change sends a fresh init with the files, so the frame remounts the new source.
 */
export function CanvasSourceEditor({
    documentUrl,
    theme,
    hasUserActivation,
    onOpenExternal,
    ...callbacks
}: CanvasSourceEditorProps): JSX.Element {
    const { entry } = useValues(canvasEditLogic)
    const { select, frameMounted, dropBlock, setText, editKey } = useActions(canvasEditLogic)
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const readyRef = useRef(false)
    const latest = useRef({ entry, theme, callbacks, hasUserActivation, onOpenExternal })
    latest.current = { entry, theme, callbacks, hasUserActivation, onOpenExternal }

    const sendInit = (): void => {
        const snapshot = latest.current.entry
        if (!snapshot || !readyRef.current) {
            return
        }
        postToCanvasEditor({
            type: 'init',
            files: snapshot.files,
            entry: CANVAS_ENTRY_PATH,
            editing: true,
            rev: snapshot.rev,
            focusBlockId: snapshot.focusBlockId,
            focusSource: snapshot.focusSource,
            theme: latest.current.theme,
            highlights: [],
        })
    }

    const handleKey = (key: CanvasEditKey, prevent?: () => void): void => {
        const mod = key.metaKey || key.ctrlKey
        if (key.key === 'Escape') {
            const drag = activeSourceDrag()
            if (drag) {
                drag.end(false)
            } else {
                select(null)
                postToCanvasEditor({ type: 'canvas-edit-deselect' })
            }
            return
        }
        if ((mod && ['z', 'd'].includes(key.key.toLowerCase())) || key.key === 'Backspace' || key.key === 'Delete') {
            prevent?.()
            editKey(key)
        }
    }

    const handleEdit = (data: CanvasEditMessage): void => {
        const rect = iframeRef.current?.getBoundingClientRect()
        const offsetX = rect?.left ?? 0
        const offsetY = rect?.top ?? 0
        switch (data.type) {
            case 'canvas-edit-select':
                select(toSelection(data.element as EditElementMessage | null), data.byPointer === true)
                return
            case 'canvas-edit-root':
                frameMounted(Number(data.rev), (data.root as SourceRange | null) ?? null)
                return
            case 'canvas-edit-drop-target':
                activeSourceDrag()?.hit((data.hit as SourceDropHit | null) ?? null)
                return
            case 'canvas-edit-drag-start': {
                const element = toSelection(data.element as EditElementMessage)
                if (element) {
                    beginSourceDrag({
                        source: { kind: 'move', selection: element },
                        startX: offsetX + Number(data.x),
                        startY: offsetY + Number(data.y),
                        onDrop: dropBlock,
                    })
                }
                return
            }
            case 'canvas-edit-pointer':
                activeSourceDrag()?.move(offsetX + Number(data.x), offsetY + Number(data.y))
                return
            case 'canvas-edit-pointer-up':
                activeSourceDrag()?.end(true)
                return
            case 'canvas-edit-pointer-cancel':
                activeSourceDrag()?.end(false)
                return
            case 'canvas-edit-key':
                handleKey({
                    key: String(data.key ?? ''),
                    metaKey: data.metaKey === true,
                    ctrlKey: data.ctrlKey === true,
                    shiftKey: data.shiftKey === true,
                })
                return
            case 'canvas-edit-text': {
                const element = toSelection(data.element as EditElementMessage)
                if (element && typeof data.text === 'string') {
                    setText(element, data.text)
                }
                return
            }
        }
    }
    const latestHandlers = useRef({ handleEdit, handleKey, sendInit })
    latestHandlers.current = { handleEdit, handleKey, sendInit }

    // A layout effect attaches the listener during commit, before the frame's one-shot "ready" can arrive.
    useLayoutEffect(() => {
        readyRef.current = false
        const route = createCanvasHostMessageRouter({
            post: (message) => bridge.post(message),
            callbacks: () => ({
                ...latest.current.callbacks,
                onDataRequest: async (method, payload) => {
                    assertCanvasCapability(latest.current.entry?.project.capabilities, method, payload)
                    if (!latest.current.callbacks.onDataRequest) {
                        throw new Error('Canvas data bridge is unavailable')
                    }
                    return latest.current.callbacks.onDataRequest(method, payload)
                },
                onReady: () => {
                    if (readyRef.current) {
                        return
                    }
                    readyRef.current = true
                    latestHandlers.current.sendInit()
                    latest.current.callbacks.onReady?.()
                },
                // Text selection is for comments, and edit mode takes the pointer for itself.
                onTextSelection: undefined,
                onCommentActivate: undefined,
            }),
            hasUserActivation: () => latest.current.hasUserActivation(),
            openExternal: (url) => latest.current.onOpenExternal(url),
        })
        const bridge = new CanvasDocumentBridge(
            iframeRef.current!,
            (data) => {
                const edit = canvasEditMessageSchema.safeParse(data)
                if (edit.success) {
                    latestHandlers.current.handleEdit(edit.data)
                    return
                }
                const parsed = canvasToHostMessageSchema.safeParse(data)
                if (parsed.success) {
                    void route(parsed.data)
                }
            },
            () => {}
        )
        const disconnect = connectCanvasEditor(iframeRef.current!, bridge.post)
        return () => {
            readyRef.current = false
            activeSourceDrag()?.end(false)
            disconnect()
            bridge.close()
        }
    }, [documentUrl])

    const rev = entry?.rev
    useEffect(() => {
        if (rev !== undefined) {
            latestHandlers.current.sendInit()
        }
    }, [rev])

    useEffect(() => {
        if (readyRef.current) {
            postToCanvasEditor({ type: 'set-theme', theme })
        }
    }, [theme])

    // Shortcuts pressed while the host has focus. The frame forwards its own through canvas-edit-key.
    useEffect(() => {
        const onKey = (event: KeyboardEvent): void => {
            if (!event.isTrusted || isTypingTarget(event.target)) {
                return
            }
            const shortcut = event.metaKey || event.ctrlKey
            if (!shortcut && event.target !== document.body) {
                return
            }
            latestHandlers.current.handleKey(
                { key: event.key, metaKey: event.metaKey, ctrlKey: event.ctrlKey, shiftKey: event.shiftKey },
                () => event.preventDefault()
            )
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    }, [])

    return (
        <div className="relative h-full w-full">
            <iframe
                ref={iframeRef}
                title="Canvas editor"
                data-canvas-source-editor=""
                // allow-scripts without allow-same-origin keeps the sandbox in an opaque origin.
                // Do not add allow-popups or allow-same-origin.
                sandbox="allow-scripts"
                key={documentUrl}
                src={`${documentUrl}#bridge=port`}
                referrerPolicy="no-referrer"
                // Without a matching color-scheme the browser paints the frame white before init lands.
                style={{ colorScheme: theme }}
                className="h-full w-full border-0 bg-background"
                data-attr="canvas-source-editor"
            />
            <SourceDragOverlay />
        </div>
    )
}
