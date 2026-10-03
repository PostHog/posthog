import { useEffect, useLayoutEffect, useRef } from 'react'

import type { CanvasCapabilitiesApi } from '../generated/api.schemas'
import { translateCanvasRect, translateCanvasTextSelection } from '../sidePanel/comments/canvasCommentThreads'
import { assertCanvasCapability } from './canvasCapabilities'
import { CanvasDocumentBridge } from './canvasDocumentBridge'
import { CanvasHostCallbacks, createCanvasHostMessageRouter } from './canvasHostMessageRouter'
import {
    CANVAS_CHANNEL,
    CanvasCommentHighlight,
    CanvasTheme,
    HostToCanvasMessage,
    canvasToHostMessageSchema,
} from './canvasProtocol'

export interface DraftCanvasProps extends CanvasHostCallbacks {
    /** The sandbox bootstrap document on the artifact origin. */
    documentUrl: string
    capabilities: CanvasCapabilitiesApi | null | undefined
    files: Record<string, string>
    entry: string
    theme: CanvasTheme
    hasUserActivation: () => boolean
    onOpenExternal: (url: string) => void
    /** Comment anchors to draw in the frame. */
    commentHighlights: CanvasCommentHighlight[]
    /** Bumped to clear the viewer's text selection in the frame, for example after they comment on it. */
    clearTextSelectionKey: number
}

/**
 * Renders unbuilt source in the sandbox document, which transpiles it in the browser.
 * The document loads by URL, not as srcdoc, because a srcdoc frame inherits the web
 * app's CSP. The source arrives over a document-bound port after the first load.
 * Every data request must be declared by the source project.
 */
export function DraftCanvas({
    documentUrl,
    capabilities,
    files,
    entry,
    theme,
    hasUserActivation,
    onOpenExternal,
    commentHighlights,
    clearTextSelectionKey,
    ...callbacks
}: DraftCanvasProps): JSX.Element {
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const bridgeRef = useRef<CanvasDocumentBridge | null>(null)
    const readyRef = useRef(false)
    const latest = useRef({
        capabilities,
        files,
        entry,
        theme,
        callbacks,
        hasUserActivation,
        onOpenExternal,
        commentHighlights,
    })
    latest.current = {
        capabilities,
        files,
        entry,
        theme,
        callbacks,
        hasUserActivation,
        onOpenExternal,
        commentHighlights,
    }

    const post = (message: HostToCanvasMessage): void => {
        bridgeRef.current?.post(message)
    }
    const postInit = (): void => {
        post({
            channel: CANVAS_CHANNEL,
            type: 'init',
            files: latest.current.files,
            entry: latest.current.entry,
            theme: latest.current.theme,
            highlights: latest.current.commentHighlights,
        })
    }

    // Attach before load so the port connects before any canvas source runs.
    useLayoutEffect(() => {
        readyRef.current = false
        const route = createCanvasHostMessageRouter({
            post,
            callbacks: () => ({
                ...latest.current.callbacks,
                onDataRequest: (method, payload) => {
                    assertCanvasCapability(latest.current.capabilities, method, payload)
                    return latest.current.callbacks.onDataRequest(method, payload)
                },
                onReady: () => {
                    if (readyRef.current) {
                        return
                    }
                    readyRef.current = true
                    postInit()
                    latest.current.callbacks.onReady?.()
                },
                onTextSelection: (selection) =>
                    latest.current.callbacks.onTextSelection?.(
                        translateCanvasTextSelection(selection, iframeRef.current?.getBoundingClientRect() ?? null)
                    ),
                onCommentActivate: (id, rect) =>
                    latest.current.callbacks.onCommentActivate?.(
                        id,
                        rect ? translateCanvasRect(rect, iframeRef.current?.getBoundingClientRect() ?? null) : null
                    ),
            }),
            hasUserActivation: () => latest.current.hasUserActivation(),
            openExternal: (url) => latest.current.onOpenExternal(url),
        })
        const bridge = new CanvasDocumentBridge(
            iframeRef.current!,
            (data) => {
                const parsed = canvasToHostMessageSchema.safeParse(data)
                if (parsed.success) {
                    void route(parsed.data)
                }
            },
            () => {}
        )
        bridgeRef.current = bridge
        return () => {
            readyRef.current = false
            bridge.close()
            bridgeRef.current = null
        }
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- a new document needs a fresh listener and ready flag
    }, [documentUrl])

    // A new init remounts the canvas app, so only a code change sends one.
    useEffect(() => {
        if (readyRef.current) {
            postInit()
        }
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- postInit reads the latest code through a ref
    }, [files, entry])

    useEffect(() => {
        if (readyRef.current) {
            post({ channel: CANVAS_CHANNEL, type: 'set-theme', theme })
        }
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- post is stable in behavior
    }, [theme])

    useEffect(() => {
        if (readyRef.current) {
            post({ channel: CANVAS_CHANNEL, type: 'set-comment-highlights', highlights: commentHighlights })
        }
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- post is stable in behavior
    }, [commentHighlights])

    useEffect(() => {
        if (readyRef.current && clearTextSelectionKey > 0) {
            post({ channel: CANVAS_CHANNEL, type: 'clear-text-selection' })
        }
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- post is stable in behavior
    }, [clearTextSelectionKey])

    return (
        <iframe
            key={documentUrl}
            ref={iframeRef}
            title="Canvas draft"
            // allow-scripts without allow-same-origin keeps the sandbox in an opaque origin.
            // Do not add allow-popups or allow-same-origin.
            sandbox="allow-scripts"
            src={`${documentUrl}#bridge=port`}
            referrerPolicy="no-referrer"
            // Without a matching color-scheme the browser paints the frame white before init lands.
            style={{ colorScheme: theme }}
            className="h-full w-full border-0 bg-background"
        />
    )
}
