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
 * (`/code/channel/<channelId>` and `/code/channel/<channelId>/tasks/<taskId>`). On mount it
 * deep-links into the desktop app via the `posthog-code(-dev)://` custom scheme; for visitors
 * without the app it shows an explanation, a manual "open" button (in case the browser blocks
 * the auto-redirect), and a download link. Visitors who can open spaces on the web also get a
 * link to the channel's space in the browser. Thread links skip it, because the web space has no thread view.
 */
export function CodeChannelLink({ channelId, taskId }: CodeChannelLinkProps): JSX.Element {
    // Null when the channel id is missing (a partial URL or params not yet resolved), since
    // firing with an empty id would send a malformed `<scheme>://channel/`.
    const deepLink = channelId ? channelDeepLink(channelId, taskId) : null
    const target = taskId ? 'thread' : 'channel'
    // The web space scene shows "Not found" without this flag, so only offer it to visitors who have it.
    const webSpacesEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    const { location } = useValues(router)
    const webUrl =
        webSpacesEnabled && channelId && !taskId ? webPath(location.pathname, urls.taskSpace(channelId)) : null

    useEffect(() => {
        if (deepLink) {
            window.location.href = deepLink
        }
    }, [deepLink])

    return (
        <BridgePage view="code-channel-link">
            <DesktopBridgeBody subject={`This ${target}`} deepLink={deepLink} webUrl={webUrl} />
        </BridgePage>
    )
}

export default CodeChannelLink
