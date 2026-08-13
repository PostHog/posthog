import { useValues } from 'kea'
import { useEffect, useLayoutEffect, useRef } from 'react'

import { themeLogic } from 'lib/logic/themeLogic'

import {
    GenUICapabilities,
    GenUITheme,
    buildGenUIArtifactHostDocument,
    createGenUIHostMessageRouter,
    readGenUIFrame,
} from './genUIArtifactBridge'
import { GenUIFrame } from './genUIFrames'

export type GenUIArtifactFrameProps = {
    artifactUrl: string
    capabilities: GenUICapabilities | undefined
    frames: Record<string, GenUIFrame>
    onError?: (message: string) => void
    onRendered?: () => void
}

export function GenUIArtifactFrame({
    artifactUrl,
    capabilities,
    frames,
    onError,
    onRendered,
}: GenUIArtifactFrameProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme: GenUITheme = isDarkModeOn ? 'dark' : 'light'
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const artifactPortRef = useRef<MessagePort | null>(null)
    const initialTheme = useRef(theme).current
    const hostDocument = buildGenUIArtifactHostDocument(artifactUrl, initialTheme)
    const latest = useRef({ capabilities, frames, onError, onRendered, theme })
    latest.current = { capabilities, frames, onError, onRendered, theme }

    useLayoutEffect(() => {
        const iframe = iframeRef.current
        const route = createGenUIHostMessageRouter(
            (message) => artifactPortRef.current?.postMessage(message),
            () => ({
                onDataRequest: (method, payload) => {
                    if (method !== 'readFrame') {
                        throw new Error(`Method "${method}" is not available in notebook visualizations`)
                    }
                    return readGenUIFrame(latest.current.capabilities, latest.current.frames, payload)
                },
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
            bridge.port1.addEventListener('message', onMessage)
            bridge.port1.start()
            // The sandboxed srcDoc has an opaque origin, so the exact iframe window plus a fresh MessagePort is the trust boundary.
            // nosemgrep: javascript.browser.security.wildcard-postmessage-configuration.wildcard-postmessage-configuration
            iframe?.contentWindow?.postMessage({ channel: 'posthog-canvas-host', type: 'connect' }, '*', [bridge.port2])
            bridge.port1.postMessage({ channel: 'posthog-canvas', type: 'set-theme', theme: latest.current.theme })
        }

        iframe?.addEventListener('load', onLoad)
        return () => {
            iframe?.removeEventListener('load', onLoad)
            artifactPortRef.current?.close()
            artifactPortRef.current = null
        }
    }, [hostDocument])

    useEffect(() => {
        artifactPortRef.current?.postMessage({ channel: 'posthog-canvas', type: 'set-theme', theme })
    }, [theme])

    return (
        <iframe
            ref={iframeRef}
            title="Generated visualization"
            sandbox="allow-scripts"
            srcDoc={hostDocument}
            referrerPolicy="no-referrer"
            className={`w-full h-full border-0 bg-primary ${
                theme === 'dark' ? '[color-scheme:dark]' : '[color-scheme:light]'
            }`}
        />
    )
}
