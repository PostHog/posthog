import { SceneExport } from 'scenes/sceneTypes'

import { DesktopHandoff } from './DesktopHandoff'
import { DESKTOP_SCHEME } from './desktopScheme'
import { useDesktopHandoff } from './useDesktopHandoff'

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
 * (`/code/channel/<channelId>` and `/code/channel/<channelId>/tasks/<taskId>`). Channels and
 * their threads only exist in the desktop app, so nothing is rendered here beyond the
 * deep-link interstitial.
 */
export function CodeChannelLink({ channelId, taskId }: CodeChannelLinkProps): JSX.Element {
    // Null when the channel id is missing (a partial URL or params not yet resolved), since
    // firing with an empty id would send a malformed `<scheme>://channel/`.
    const deepLink = channelId ? channelDeepLink(channelId, taskId) : null
    const { status, retry } = useDesktopHandoff(deepLink)

    return (
        <DesktopHandoff
            status={status}
            onRetry={retry}
            description={`This ${taskId ? 'thread' : 'channel'} lives in the PostHog Desktop app.`}
            view="code-channel-link"
        />
    )
}

export default CodeChannelLink
