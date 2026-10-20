import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DesktopBridgeBody } from './DesktopBridgeBody'
import { DESKTOP_SCHEME } from './desktopScheme'
import { webPath } from './webPath'

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

function canvasDeepLink(channelId: string, dashboardId: string): string {
    return `${DESKTOP_SCHEME}://canvas/${encodeURIComponent(channelId)}/${encodeURIComponent(dashboardId)}`
}

/**
 * Public, unauthenticated bridge for desktop-app "canvas" share links
 * (`/code/canvas/<channelId>/<dashboardId>`). On mount it deep-links into the desktop
 * app via the `posthog-code(-dev)://` custom scheme; for visitors without the app it
 * shows an explanation, a manual "open" button (in case the browser blocks the
 * auto-redirect), and a download link. Visitors who can open canvases on the web also
 * get a link to the canvas in the browser.
 */
export function CodeCanvasLink({ channelId, dashboardId }: CodeCanvasLinkProps): JSX.Element {
    // Null when a param is missing (a partial URL or params not yet resolved) —
    // firing with an empty id would send a malformed `<scheme>://canvas//`.
    const deepLink = channelId && dashboardId ? canvasDeepLink(channelId, dashboardId) : null
    // The web canvas scene shows "Not found" without this flag, so only offer it to visitors who have it.
    const webCanvasEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    const { location } = useValues(router)
    const webUrl = webCanvasEnabled && dashboardId ? webPath(location.pathname, urls.canvasDetail(dashboardId)) : null

    useEffect(() => {
        if (deepLink) {
            window.location.href = deepLink
        }
    }, [deepLink])

    return (
        <BridgePage view="code-canvas-link">
            <DesktopBridgeBody subject="This canvas" deepLink={deepLink} webUrl={webUrl} />
        </BridgePage>
    )
}

export default CodeCanvasLink
