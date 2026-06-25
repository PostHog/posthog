import { useEffect } from 'react'

import { IconLaptop } from '@posthog/icons'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'

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

/**
 * Public, unauthenticated bridge for desktop-app "canvas" share links
 * (`/code/canvas/<channelId>/<dashboardId>`). On mount it deep-links into the desktop
 * app via the `posthog-code://` custom scheme; for visitors without the app installed it
 * shows a short explanation and a download link. The canvas itself only exists in the
 * desktop app, so nothing is rendered here beyond this interstitial.
 */
export function CodeCanvasLink({ channelId, dashboardId }: CodeCanvasLinkProps): JSX.Element {
    useEffect(() => {
        // Production custom scheme only — the public website has no dev build to target.
        window.location.href = `posthog-code://canvas/${encodeURIComponent(channelId)}/${encodeURIComponent(
            dashboardId
        )}`
    }, [channelId, dashboardId])

    return (
        <BridgePage view="code-canvas-link">
            <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
                <IconLaptop className="text-5xl shrink-0" />
                <h2 className="text-xl font-semibold m-0">Opening in PostHog Code…</h2>
                <p className="text-muted mb-0">
                    Canvases live in the PostHog Code desktop app. If it's installed, it should open
                    automatically. Otherwise, download it to view this canvas.
                </p>
                <LemonButton type="primary" to="https://posthog.com/code" targetBlank>
                    Download PostHog Code
                </LemonButton>
            </div>
        </BridgePage>
    )
}

export default CodeCanvasLink
