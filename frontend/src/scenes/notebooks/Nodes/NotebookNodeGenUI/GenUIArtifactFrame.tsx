import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { themeLogic } from 'lib/logic/themeLogic'

import type { GenUIFrameApi } from 'products/notebooks/frontend/generated/api.schemas'

import { createGenUIHostMessageRouter, readGenUIFrame } from './genUIArtifactBridge'

export type GenUIArtifactFrameProps = {
    artifactUrl: string
    allowedFrames: string[]
    onReadFrame: (name: string) => Promise<GenUIFrameApi>
    onArtifactUnavailable?: () => void
    onError?: () => void
    onRendered?: () => void
}

export function GenUIArtifactFrame({
    artifactUrl,
    allowedFrames,
    onReadFrame,
    onArtifactUnavailable,
    onError,
    onRendered,
}: GenUIArtifactFrameProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = isDarkModeOn ? 'dark' : 'light'
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const artifactPortRef = useRef<MessagePort | null>(null)
    const renderTimeoutRef = useRef<number | null>(null)
    const initialTheme = useRef(theme).current
    const latest = useRef({ allowedFrames, onArtifactUnavailable, onError, onReadFrame, onRendered, theme })
    latest.current = { allowedFrames, onArtifactUnavailable, onError, onReadFrame, onRendered, theme }

    const themedArtifactUrl = new URL(artifactUrl)
    themedArtifactUrl.hash = `theme=${initialTheme}`

    const clearConnection = (): void => {
        artifactPortRef.current?.close()
        artifactPortRef.current = null
        if (renderTimeoutRef.current !== null) {
            window.clearTimeout(renderTimeoutRef.current)
            renderTimeoutRef.current = null
        }
    }

    const connect = (): void => {
        clearConnection()
        const iframeWindow = iframeRef.current?.contentWindow
        if (!iframeWindow) {
            latest.current.onArtifactUnavailable?.()
            return
        }
        const bridge = new MessageChannel()
        artifactPortRef.current = bridge.port1
        const route = createGenUIHostMessageRouter(
            (message) => bridge.port1.postMessage(message),
            () => ({
                onDataRequest: (_method, payload) =>
                    readGenUIFrame(latest.current.allowedFrames, latest.current.onReadFrame, payload),
                onError: () => latest.current.onError?.(),
                onRendered: () => {
                    if (renderTimeoutRef.current !== null) {
                        window.clearTimeout(renderTimeoutRef.current)
                        renderTimeoutRef.current = null
                    }
                    latest.current.onRendered?.()
                },
            })
        )
        bridge.port1.addEventListener('message', (event) => void route(event.data))
        bridge.port1.start()
        // A sandboxed artifact has an opaque origin; the exact iframe window and one-use port form the trust boundary.
        // nosemgrep: javascript.browser.security.wildcard-postmessage-configuration.wildcard-postmessage-configuration
        iframeWindow.postMessage({ channel: 'posthog-canvas', type: 'connect' }, '*', [bridge.port2])
        bridge.port1.postMessage({ channel: 'posthog-canvas', type: 'set-theme', theme: latest.current.theme })
        renderTimeoutRef.current = window.setTimeout(() => latest.current.onArtifactUnavailable?.(), 20_000)
    }

    useEffect(() => clearConnection, [])

    useEffect(() => {
        artifactPortRef.current?.postMessage({ channel: 'posthog-canvas', type: 'set-theme', theme })
    }, [theme])

    return (
        <iframe
            ref={iframeRef}
            title="Generated visualization"
            sandbox="allow-scripts"
            src={themedArtifactUrl.href}
            referrerPolicy="no-referrer"
            className={`w-full h-full border-0 bg-primary ${
                theme === 'dark' ? '[color-scheme:dark]' : '[color-scheme:light]'
            }`}
            onLoad={connect}
            onError={() => onArtifactUnavailable?.()}
        />
    )
}
