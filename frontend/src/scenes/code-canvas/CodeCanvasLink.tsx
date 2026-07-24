import { useEffect } from 'react'

import { IconLaptop } from '@posthog/icons'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'

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

function canvasDeepLink(channelId: string, dashboardId: string): string {
    return `${DESKTOP_SCHEME}://canvas/${encodeURIComponent(channelId)}/${encodeURIComponent(dashboardId)}`
}

/**
 * Public, unauthenticated bridge for desktop-app "canvas" share links
 * (`/code/canvas/<channelId>/<dashboardId>`). On mount it deep-links into the desktop
 * app via the `posthog-code(-dev)://` custom scheme; for visitors without the app it
 * shows an explanation, a manual "open" button (in case the browser blocks the
 * auto-redirect), and a download link. The canvas itself only exists in the desktop
 * app, so nothing is rendered here beyond this interstitial.
 */
export function CodeCanvasLink({ channelId, dashboardId }: CodeCanvasLinkProps): JSX.Element {
    // Null when a param is missing (a partial URL or params not yet resolved) —
    // firing with an empty id would send a malformed `<scheme>://canvas//`.
    const deepLink = channelId && dashboardId ? canvasDeepLink(channelId, dashboardId) : null

    useEffect(() => {
        if (deepLink) {
            window.location.href = deepLink
        }
    }, [deepLink])

    return (
        <BridgePage view="code-canvas-link">
            <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
                <IconLaptop className="text-5xl shrink-0" />
                <h2 className="text-xl font-semibold m-0">Opening in PostHog Code…</h2>
                <p className="text-muted mb-0">
                    Canvases live in the PostHog Code desktop app. If it's installed, it should open automatically. If
                    it didn't, use the button below — or download the app.
                </p>
                <div className="flex flex-col items-center gap-2">
                    {deepLink && (
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                window.location.href = deepLink
                            }}
                        >
                            Open in PostHog Code
                        </LemonButton>
                    )}
                    <LemonButton type="secondary" to="https://posthog.com/code" targetBlank>
                        Download PostHog Code
                    </LemonButton>
                </div>
            </div>
        </BridgePage>
    )
}

export default CodeCanvasLink
