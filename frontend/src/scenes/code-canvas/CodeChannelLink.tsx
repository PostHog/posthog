import { useEffect } from 'react'

import { IconLaptop } from '@posthog/icons'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'

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
 * (`/code/channel/<channelId>` and `/code/channel/<channelId>/tasks/<taskId>`). On mount it
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
            <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
                <IconLaptop className="text-5xl shrink-0" />
                <h2 className="text-xl font-semibold m-0">Opening in PostHog Code…</h2>
                <p className="text-muted mb-0">
                    This {target} lives in the PostHog Code desktop app. If it's installed, it should open
                    automatically. If it didn't, use the button below, or download the app.
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

export default CodeChannelLink
