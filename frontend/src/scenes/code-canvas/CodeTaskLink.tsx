import { useEffect } from 'react'

import { IconLaptop } from '@posthog/icons'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'

import { DESKTOP_SCHEME } from './desktopScheme'

export interface CodeTaskLinkProps {
    taskId: string
    commentId?: string
    commentScope?: string
    commentItemId?: string
}

export const scene: SceneExport<CodeTaskLinkProps> = {
    component: CodeTaskLink,
    paramsToProps: ({ params: { taskId }, searchParams }) => ({
        taskId: taskId ?? '',
        commentId: searchParams.comment || undefined,
        commentScope: searchParams.scope || undefined,
        commentItemId: searchParams.item || undefined,
    }),
}

function taskDeepLink({ taskId, commentId, commentScope, commentItemId }: CodeTaskLinkProps): string {
    const params = new URLSearchParams()
    if (commentId) {
        params.set('comment', commentId)
    }
    if (commentScope) {
        params.set('scope', commentScope)
    }
    if (commentItemId) {
        params.set('item', commentItemId)
    }
    const query = params.toString()
    return `${DESKTOP_SCHEME}://task/${encodeURIComponent(taskId)}${query ? `?${query}` : ''}`
}

export function CodeTaskLink(props: CodeTaskLinkProps): JSX.Element {
    const deepLink = props.taskId ? taskDeepLink(props) : null

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
