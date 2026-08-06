import { useValues } from 'kea'
import { useEffect, useLayoutEffect, useRef } from 'react'

import { themeLogic } from 'lib/logic/themeLogic'

import {
    CanvasCapabilities,
    CanvasTheme,
    buildCanvasArtifactHostDocument,
    createCanvasHostMessageRouter,
} from './canvasArtifactBridge'
import { handleCanvasDataRequest } from './canvasDataRequest'

export interface CanvasArtifactFrameProps {
    artifactUrl: string
    /** The published manifest's frozen capabilities. Missing manifests deny
     * all data requests. */
    capabilities: CanvasCapabilities | undefined
    onError?: (message: string) => void
    onRendered?: () => void
}

/** Renders a published canvas build in a double-sandboxed iframe and serves
 * its `ph.*` data requests over a MessagePort bridge. */
export function CanvasArtifactFrame({
    artifactUrl,
    capabilities,
    onError,
    onRendered,
}: CanvasArtifactFrameProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme: CanvasTheme = isDarkModeOn ? 'dark' : 'light'
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const artifactPortRef = useRef<MessagePort | null>(null)
    // The srcDoc bakes in the mount-time theme only - folding the live theme
    // in would reload the artifact on every toggle. Live changes go over the port.
    const initialTheme = useRef(theme).current
    const hostDocument = buildCanvasArtifactHostDocument(artifactUrl, initialTheme)
    const latest = useRef({ capabilities, onError, onRendered, theme })
    latest.current = { capabilities, onError, onRendered, theme }

    useLayoutEffect(() => {
        const iframe = iframeRef.current
        const route = createCanvasHostMessageRouter(
            (message) => artifactPortRef.current?.postMessage(message),
            () => ({
                onDataRequest: (method, payload) =>
                    handleCanvasDataRequest(method, payload, latest.current.capabilities),
                onError: (message) => latest.current.onError?.(message),
                onRendered: () => latest.current.onRendered?.(),
            })
        )

        const onMessage = (event: MessageEvent): void => {
            void route(event.data)
        }

        const onLoad = (): void => {
            if (artifactPortRef.current) {
                return
            }
            const bridge = new MessageChannel()
            artifactPortRef.current = bridge.port1
            artifactPortRef.current.addEventListener('message', onMessage)
            artifactPortRef.current.start()
            iframe?.contentWindow?.postMessage({ channel: 'posthog-canvas-host', type: 'connect' }, '*', [bridge.port2])
            // Queued on the port until the artifact runtime starts it, so the
            // first themed paint happens before any data renders.
            artifactPortRef.current.postMessage({
                channel: 'posthog-canvas',
                type: 'set-theme',
                theme: latest.current.theme,
            })
        }

        iframe?.addEventListener('load', onLoad)
        return () => {
            iframe?.removeEventListener('load', onLoad)
            artifactPortRef.current?.close()
            artifactPortRef.current = null
        }
        // oxlint-disable-next-line exhaustive-deps -- a new host document needs a fresh bridge
    }, [hostDocument])

    // Live theme change: re-theme the running artifact without reloading it.
    useEffect(() => {
        artifactPortRef.current?.postMessage({ channel: 'posthog-canvas', type: 'set-theme', theme })
    }, [theme])

    return (
        <iframe
            ref={iframeRef}
            title="Canvas"
            sandbox="allow-scripts"
            srcDoc={hostDocument}
            referrerPolicy="no-referrer"
            // Without a matching color-scheme the UA paints the embedded
            // documents' base canvas opaque white, flashing over dark mode.
            style={{ colorScheme: theme }}
            className="w-full h-full border-0 bg-primary"
        />
    )
}
