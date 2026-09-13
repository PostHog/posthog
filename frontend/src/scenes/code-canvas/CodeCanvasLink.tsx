import { SceneExport } from 'scenes/sceneTypes'

import { DesktopHandoff } from './DesktopHandoff'
import { DESKTOP_SCHEME } from './desktopScheme'
import { useDesktopHandoff } from './useDesktopHandoff'

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
 * (`/code/canvas/<channelId>/<dashboardId>`). The canvas itself only exists in the desktop
 * app, so nothing is rendered here beyond the deep-link interstitial.
 */
export function CodeCanvasLink({ channelId, dashboardId }: CodeCanvasLinkProps): JSX.Element {
    // Null when a param is missing (a partial URL or params not yet resolved) —
    // firing with an empty id would send a malformed `<scheme>://canvas//`.
    const deepLink = channelId && dashboardId ? canvasDeepLink(channelId, dashboardId) : null
    const { status, retry } = useDesktopHandoff(deepLink)

    return (
        <DesktopHandoff
            status={status}
            onRetry={retry}
            description="Canvases live in the PostHog Desktop app."
            view="code-canvas-link"
        />
    )
}

export default CodeCanvasLink
