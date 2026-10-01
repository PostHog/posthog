import { useEffect, useLayoutEffect, useMemo, useRef } from 'react'

import type { CanvasCapabilitiesApi } from '../generated/api.schemas'
import { assertCanvasCapability } from './canvasCapabilities'
import { CanvasHostCallbacks, createCanvasHostMessageRouter } from './canvasHostMessageRouter'
import { CANVAS_CHANNEL, CanvasTheme, HostToCanvasMessage, canvasToHostMessageSchema } from './canvasProtocol'

export interface BuiltCanvasProps extends CanvasHostCallbacks {
    /** The signed URL of the build's entry HTML, on the artifact origin. */
    artifactUrl: string
    /** The capabilities frozen into the build. A missing manifest denies every data request. */
    capabilities: CanvasCapabilitiesApi | null | undefined
    theme: CanvasTheme
    hasUserActivation: () => boolean
    onOpenExternal: (url: string) => void
}

/** The artifact URL with the theme in its fragment, which never reaches the server. */
export function themedArtifactUrl(artifactUrl: string, theme: CanvasTheme): string {
    const url = new URL(artifactUrl)
    url.hash = new URLSearchParams({ theme }).toString()
    return url.href
}

/**
 * Renders a published build. The iframe loads the signed artifact URL directly: a
 * srcdoc host document would inherit the web app's CSP, which blocks its inline script.
 * On load the host hands the artifact a MessagePort, and every message after that goes
 * over the port.
 */
export function BuiltCanvas({
    artifactUrl,
    capabilities,
    theme,
    hasUserActivation,
    onOpenExternal,
    ...callbacks
}: BuiltCanvasProps): JSX.Element {
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const portRef = useRef<MessagePort | null>(null)
    // The theme reaches the first paint through the fragment. Later changes go over the
    // port, so a theme toggle does not reload the artifact.
    const initialTheme = useRef(theme).current
    const src = useMemo(() => themedArtifactUrl(artifactUrl, initialTheme), [artifactUrl, initialTheme])
    const latest = useRef({ capabilities, callbacks, theme, onOpenExternal, hasUserActivation })
    latest.current = { capabilities, callbacks, theme, onOpenExternal, hasUserActivation }

    useLayoutEffect(() => {
        const iframe = iframeRef.current
        let loads = 0
        const post = (message: HostToCanvasMessage): void => portRef.current?.postMessage(message)
        const route = createCanvasHostMessageRouter({
            post,
            callbacks: () => ({
                ...latest.current.callbacks,
                onDataRequest: (method, payload) => {
                    // Gating here means every consumer of a build gets it.
                    assertCanvasCapability(latest.current.capabilities, method, payload)
                    return latest.current.callbacks.onDataRequest(method, payload)
                },
            }),
            hasUserActivation: () => latest.current.hasUserActivation(),
            openExternal: (url) => latest.current.onOpenExternal(url),
        })
        const onPortMessage = (event: MessageEvent): void => {
            const parsed = canvasToHostMessageSchema.safeParse(event.data)
            if (parsed.success) {
                void route(parsed.data)
            }
        }
        const dropPort = (): void => {
            portRef.current?.close()
            portRef.current = null
        }
        const onLoad = (): void => {
            loads += 1
            // A second load means the artifact navigated away from itself. Whatever loaded
            // now is not the build, so it gets no bridge.
            if (loads > 1) {
                dropPort()
                return
            }
            const bridge = new MessageChannel()
            portRef.current = bridge.port1
            bridge.port1.addEventListener('message', onPortMessage)
            bridge.port1.start()
            // The sandboxed artifact has an opaque origin, so no narrower target origin matches it.
            iframe?.contentWindow?.postMessage({ channel: CANVAS_CHANNEL, type: 'connect' }, '*', [bridge.port2])
            post({ channel: CANVAS_CHANNEL, type: 'set-theme', theme: latest.current.theme })
        }
        iframe?.addEventListener('load', onLoad)
        return () => {
            iframe?.removeEventListener('load', onLoad)
            dropPort()
        }
    }, [src])

    useEffect(() => {
        portRef.current?.postMessage({ channel: CANVAS_CHANNEL, type: 'set-theme', theme })
    }, [theme])

    return (
        <iframe
            ref={iframeRef}
            title="Canvas"
            // allow-scripts without allow-same-origin keeps the artifact in an opaque origin.
            // Do not add allow-popups or allow-same-origin.
            sandbox="allow-scripts"
            src={src}
            referrerPolicy="no-referrer"
            // Without a matching color-scheme the browser paints the frame white before the artifact's styles land.
            style={{ colorScheme: theme }}
            className="h-full w-full border-0 bg-background"
        />
    )
}
