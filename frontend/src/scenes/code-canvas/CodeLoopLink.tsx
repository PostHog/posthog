import { useEffect } from 'react'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SceneExport } from 'scenes/sceneTypes'

import { DesktopBridgeBody } from './DesktopBridgeBody'
import { DESKTOP_SCHEME } from './desktopScheme'

export interface CodeLoopLinkProps {
    loopId: string
}

export const scene: SceneExport<CodeLoopLinkProps> = {
    component: CodeLoopLink,
    paramsToProps: ({ params: { loopId } }) => ({
        loopId: loopId ?? '',
    }),
}

export function loopDeepLink(loopId: string): string {
    return `${DESKTOP_SCHEME}://loop/${encodeURIComponent(loopId)}`
}

/**
 * Public, unauthenticated bridge for desktop-app "loop" links (`/code/loop/<loopId>`). On mount it
 * deep-links into the desktop app via the `posthog-code(-dev)://` custom scheme; for visitors
 * without the app it shows an explanation, a manual "open" button (in case the browser blocks
 * the auto-redirect), and a download link. Loops only exist in the desktop app, so nothing is
 * rendered here beyond this interstitial.
 */
export function CodeLoopLink({ loopId }: CodeLoopLinkProps): JSX.Element {
    // Null when the loop id is missing (a partial URL or params not yet resolved), since firing
    // with an empty id would send a malformed `<scheme>://loop/`.
    const deepLink = loopId ? loopDeepLink(loopId) : null

    useEffect(() => {
        if (deepLink) {
            window.location.href = deepLink
        }
    }, [deepLink])

    return (
        <BridgePage view="code-loop-link">
            <DesktopBridgeBody subject="This loop" deepLink={deepLink} />
        </BridgePage>
    )
}

export default CodeLoopLink
