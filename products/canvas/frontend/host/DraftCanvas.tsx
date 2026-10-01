import { useEffect, useLayoutEffect, useRef } from 'react'

import { CanvasHostCallbacks, createCanvasHostMessageRouter } from './canvasHostMessageRouter'
import { CANVAS_CHANNEL, CanvasTheme, HostToCanvasMessage, canvasToHostMessageSchema } from './canvasProtocol'

export interface DraftCanvasProps extends CanvasHostCallbacks {
    /** The sandbox bootstrap document on the artifact origin. */
    documentUrl: string
    /** The single-file React source to render. */
    code: string
    theme: CanvasTheme
    hasUserActivation: () => boolean
    onOpenExternal: (url: string) => void
}

/**
 * Renders unbuilt source in the sandbox document, which transpiles it in the browser.
 * The document loads by URL, not as srcdoc, because a srcdoc frame inherits the web
 * app's CSP. The source arrives by postMessage once the document says it is ready.
 * This tier is ungated by design: it only runs a canvas's own head source.
 */
export function DraftCanvas({
    documentUrl,
    code,
    theme,
    hasUserActivation,
    onOpenExternal,
    ...callbacks
}: DraftCanvasProps): JSX.Element {
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const readyRef = useRef(false)
    const latest = useRef({ code, theme, callbacks, hasUserActivation, onOpenExternal })
    latest.current = { code, theme, callbacks, hasUserActivation, onOpenExternal }

    const post = (message: HostToCanvasMessage): void => {
        // The sandbox has an opaque origin, so no narrower target origin matches it.
        iframeRef.current?.contentWindow?.postMessage(message, '*')
    }
    const postInit = (): void => {
        post({ channel: CANVAS_CHANNEL, type: 'init', code: latest.current.code, theme: latest.current.theme })
    }

    // A layout effect attaches the listener during commit, before the frame's one-shot
    // "ready" can arrive and be lost.
    useLayoutEffect(() => {
        readyRef.current = false
        const route = createCanvasHostMessageRouter({
            post,
            callbacks: () => ({
                ...latest.current.callbacks,
                onReady: () => {
                    readyRef.current = true
                    postInit()
                    latest.current.callbacks.onReady?.()
                },
            }),
            hasUserActivation: () => latest.current.hasUserActivation(),
            openExternal: (url) => latest.current.onOpenExternal(url),
        })
        const onMessage = (event: MessageEvent): void => {
            // An opaque origin cannot be checked, so the frame is identified by its window.
            if (event.source !== iframeRef.current?.contentWindow) {
                return
            }
            const parsed = canvasToHostMessageSchema.safeParse(event.data)
            if (parsed.success) {
                void route(parsed.data)
            }
        }
        window.addEventListener('message', onMessage)
        return () => window.removeEventListener('message', onMessage)
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- a new document needs a fresh listener and ready flag
    }, [documentUrl])

    // A new init remounts the canvas app, so only a code change sends one.
    useEffect(() => {
        if (readyRef.current) {
            postInit()
        }
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- postInit reads the latest code through a ref
    }, [code])

    useEffect(() => {
        if (readyRef.current) {
            post({ channel: CANVAS_CHANNEL, type: 'set-theme', theme })
        }
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- post is stable in behavior
    }, [theme])

    return (
        <iframe
            ref={iframeRef}
            title="Canvas draft"
            // allow-scripts without allow-same-origin keeps the sandbox in an opaque origin.
            // Do not add allow-popups or allow-same-origin.
            sandbox="allow-scripts"
            src={documentUrl}
            referrerPolicy="no-referrer"
            // By load the document's bootstrap has run, so init reaches it even if "ready" was missed.
            onLoad={() => {
                readyRef.current = true
                postInit()
            }}
            // Without a matching color-scheme the browser paints the frame white before init lands.
            style={{ colorScheme: theme }}
            className="h-full w-full border-0 bg-background"
        />
    )
}
