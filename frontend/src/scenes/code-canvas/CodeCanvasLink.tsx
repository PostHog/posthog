import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SceneExport } from 'scenes/sceneTypes'

import { DesktopBridgeBody } from './DesktopBridgeBody'
import { DESKTOP_SCHEME } from './desktopScheme'

export interface CodeCanvasLinkProps {
    channelId: string
    dashboardId: string
}

export const scene: SceneExport<CodeCanvasLinkProps> = {
    component: CodeCanvasLink,
    paramsToProps: ({ params: { channelId, dashboardId } }) => ({
        channelId: channelId ?? '',
        dashboardId: dashboardId ?? '',
    }),
}

export function canvasDeepLink(channelId: string, dashboardId: string, searchParams: Record<string, unknown>): string {
    const base = `${DESKTOP_SCHEME}://canvas/${encodeURIComponent(channelId)}/${encodeURIComponent(dashboardId)}`
    // A "link to a copy" carries fork=1; the app then copies the canvas instead of opening it.
    return searchParams.fork === '1' || searchParams.fork === 1 ? `${base}?fork=1` : base
}

/**
 * Public, unauthenticated bridge for desktop-app "canvas" share links
 * (`/desktop/canvas/<channelId>/<dashboardId>`). On mount it deep-links into the desktop
 * app via the `posthog-code(-dev)://` custom scheme; for visitors without the app it
 * shows an explanation, a manual "open" button (in case the browser blocks the
 * auto-redirect), and a download link. The canvas itself only exists in the desktop
 * app, so nothing is rendered here beyond this interstitial.
 */
export function CodeCanvasLink({ channelId, dashboardId }: CodeCanvasLinkProps): JSX.Element {
    const { searchParams } = useValues(router)
    // Null when a param is missing (a partial URL or params not yet resolved) —
    // firing with an empty id would send a malformed `<scheme>://canvas//`.
    const deepLink = channelId && dashboardId ? canvasDeepLink(channelId, dashboardId, searchParams) : null

    useEffect(() => {
        if (deepLink) {
            window.location.href = deepLink
        }
    }, [deepLink])

    return (
        <BridgePage view="code-canvas-link">
            <DesktopBridgeBody subject="This canvas" deepLink={deepLink} />
        </BridgePage>
    )
}

export default CodeCanvasLink
