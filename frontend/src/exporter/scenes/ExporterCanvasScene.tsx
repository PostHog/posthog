import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { themeLogic } from 'lib/logic/themeLogic'

import { SharedCanvasPayload } from '../types'

const CANVAS_CHANNEL = 'posthog-canvas'
// The error every data verb (ph.query, ph.state, ...) gets on a public page: there is no
// viewer session to run queries as, so the canvas has to render without live data.
export const SHARED_VIEW_ERROR = 'unavailable_in_shared_view'

type CanvasTheme = 'light' | 'dark'

/**
 * The artifact runtime reads the theme off the URL fragment before first paint, so the
 * first frame is already themed. Fragments never reach the server, so the signed URL stays valid.
 */
export function artifactUrlWithTheme(artifactUrl: string, theme: CanvasTheme): string {
    const url = new URL(artifactUrl)
    url.hash = new URLSearchParams({ theme }).toString()
    return url.href
}

export default function ExporterCanvasScene({
    canvas,
    forcedTheme,
}: {
    canvas: SharedCanvasPayload
    forcedTheme: CanvasTheme | null
}): JSX.Element {
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const portRef = useRef<MessagePort | null>(null)
    // The same value `useThemedHtml` puts on the page, so the canvas never renders
    // dark inside a light page when the share carries no theme of its own.
    const { isDarkModeOn } = useValues(themeLogic)
    const theme: CanvasTheme = forcedTheme ?? (isDarkModeOn ? 'dark' : 'light')
    const artifactUrl = canvas.artifact_url

    useEffect(() => {
        const iframe = iframeRef.current
        if (!iframe || !artifactUrl) {
            return
        }
        const onPortMessage = (event: MessageEvent): void => {
            const data = event.data
            if (!data || data.channel !== CANVAS_CHANNEL) {
                return
            }
            if (data.type === 'data-request' && typeof data.id === 'string') {
                portRef.current?.postMessage({
                    channel: CANVAS_CHANNEL,
                    type: 'data-response',
                    id: data.id,
                    ok: false,
                    error: SHARED_VIEW_ERROR,
                })
            }
        }
        const onLoad = (): void => {
            if (portRef.current) {
                return
            }
            const bridge = new MessageChannel()
            portRef.current = bridge.port1
            bridge.port1.addEventListener('message', onPortMessage)
            bridge.port1.start()
            // The sandboxed artifact has an opaque origin, so a wildcard is the only target that
            // reaches it. The message carries no data, only the port the canvas talks back on.
            // nosemgrep: javascript.browser.security.wildcard-postmessage-configuration.wildcard-postmessage-configuration
            iframe.contentWindow?.postMessage({ channel: CANVAS_CHANNEL, type: 'connect' }, '*', [bridge.port2])
            bridge.port1.postMessage({ channel: CANVAS_CHANNEL, type: 'set-theme', theme })
        }
        iframe.addEventListener('load', onLoad)
        return () => {
            iframe.removeEventListener('load', onLoad)
            portRef.current?.close()
            portRef.current = null
        }
        // The theme only needs a fresh bridge when the artifact URL changes; live theme changes go over the port below.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [artifactUrl])

    useEffect(() => {
        portRef.current?.postMessage({ channel: CANVAS_CHANNEL, type: 'set-theme', theme })
    }, [theme])

    if (!artifactUrl) {
        return (
            <LemonBanner type="info" className="m-4">
                {canvas.published
                    ? "This canvas can't be shown right now. Try again later."
                    : 'The shared version of this canvas is no longer available. Ask its owner to share it again.'}
            </LemonBanner>
        )
    }

    return (
        <iframe
            ref={iframeRef}
            title={canvas.name || 'Canvas'}
            sandbox="allow-scripts"
            src={artifactUrlWithTheme(artifactUrl, theme)}
            referrerPolicy="no-referrer"
            className="SharedCanvas-frame"
            style={{ colorScheme: theme }}
        />
    )
}
