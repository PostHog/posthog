import { useEffect } from 'react'

import { IconLaptop } from '@posthog/icons'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'

import { DESKTOP_SCHEME } from './desktopScheme'

export interface CodeTaskLinkProps {
    taskId: string
}

export const scene: SceneExport<CodeTaskLinkProps> = {
    component: CodeTaskLink,
    paramsToProps: ({ params: { taskId } }) => ({
        taskId: taskId ?? '',
    }),
}

/**
 * Public, unauthenticated bridge for desktop-app "task" share links (`/code/task/<taskId>`),
 * used by notifications sent outside the app (e.g. comment Slack DMs). On mount it deep-links
 * into the desktop app via the `posthog-code(-dev)://` custom scheme; for visitors without the
 * app it shows an explanation, a manual "open" button (in case the browser blocks the
 * auto-redirect), and a download link.
 */
export function CodeTaskLink({ taskId }: CodeTaskLinkProps): JSX.Element {
    // Null when the task id is missing (a partial URL or params not yet resolved), since firing
    // with an empty id would send a malformed `<scheme>://task/`.
    const deepLink = taskId ? `${DESKTOP_SCHEME}://task/${encodeURIComponent(taskId)}` : null

    useEffect(() => {
        if (deepLink) {
            window.location.href = deepLink
        }
    }, [deepLink])

    return (
        <BridgePage view="code-task-link">
            <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
                <IconLaptop className="text-5xl shrink-0" />
                <h2 className="text-xl font-semibold m-0">Opening in PostHog Desktop…</h2>
                <p className="text-muted mb-0">
                    This task lives in the PostHog Desktop app. If it's installed, it should open automatically. If it
                    didn't, use the button below, or download the app.
                </p>
                <div className="flex flex-col items-center gap-2">
                    {deepLink && (
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                window.location.href = deepLink
                            }}
                        >
                            Open in PostHog Desktop
                        </LemonButton>
                    )}
                    <LemonButton type="secondary" to="https://posthog.com/desktop" targetBlank>
                        Download PostHog Desktop
                    </LemonButton>
                </div>
            </div>
        </BridgePage>
    )
}

export default CodeTaskLink
