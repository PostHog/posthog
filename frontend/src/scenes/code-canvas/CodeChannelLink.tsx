import { useEffect } from 'react'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SceneExport } from 'scenes/sceneTypes'

import { DesktopBridgeBody } from './DesktopBridgeBody'
import { DESKTOP_SCHEME } from './desktopScheme'

export interface CodeChannelLinkProps {
    channelId: string
    taskId?: string
}

export const scene: SceneExport<CodeChannelLinkProps> = {
    component: CodeChannelLink,
    paramsToProps: ({ params: { channelId, taskId } }) => ({
        channelId: channelId ?? '',
        taskId: taskId || undefined,
    }),
}

function channelDeepLink(channelId: string, taskId?: string): string {
    const base = `${DESKTOP_SCHEME}://channel/${encodeURIComponent(channelId)}`
    return taskId ? `${base}/tasks/${encodeURIComponent(taskId)}` : base
}

/**
 * Public, unauthenticated bridge for desktop-app "channel" share links
 * (`/desktop/channel/<channelId>` and `/desktop/channel/<channelId>/tasks/<taskId>`). On mount it
 * deep-links into the desktop app via the `posthog-code(-dev)://` custom scheme; for visitors
 * without the app it shows an explanation, a manual "open" button (in case the browser blocks
 * the auto-redirect), and a download link. Channels and their threads only exist in the desktop
 * app, so nothing is rendered here beyond this interstitial.
 */
export function CodeChannelLink({ channelId, taskId }: CodeChannelLinkProps): JSX.Element {
    // Null when the channel id is missing (a partial URL or params not yet resolved), since
    // firing with an empty id would send a malformed `<scheme>://channel/`.
    const deepLink = channelId ? channelDeepLink(channelId, taskId) : null
    const target = taskId ? 'thread' : 'channel'

    useEffect(() => {
        if (deepLink) {
            window.location.href = deepLink
        }
    }, [deepLink])

    return (
        <BridgePage view="code-channel-link">
            <DesktopBridgeBody subject={`This ${target}`} deepLink={deepLink} />
        </BridgePage>
    )
}

export default CodeChannelLink
