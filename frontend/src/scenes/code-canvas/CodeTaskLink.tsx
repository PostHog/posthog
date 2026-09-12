import { useValues } from 'kea'
import { router } from 'kea-router'

import { SceneExport } from 'scenes/sceneTypes'

import { DesktopHandoff } from './DesktopHandoff'
import { DESKTOP_SCHEME } from './desktopScheme'
import { useDesktopHandoff } from './useDesktopHandoff'

export interface CodeTaskLinkProps {
    taskId: string
}

export const scene: SceneExport<CodeTaskLinkProps> = {
    component: CodeTaskLink,
    paramsToProps: ({ params: { taskId } }) => ({
        taskId: taskId ?? '',
    }),
}

export function taskDeepLink(taskId: string, searchParams: Record<string, unknown>): string {
    const params = new URLSearchParams()
    if (typeof searchParams.comment === 'string') {
        params.set('comment', searchParams.comment)
    }
    if (typeof searchParams.scope === 'string') {
        params.set('scope', searchParams.scope)
    }
    if (typeof searchParams.item === 'string') {
        params.set('item', searchParams.item)
    }
    const query = params.toString()
    return `${DESKTOP_SCHEME}://task/${encodeURIComponent(taskId)}${query ? `?${query}` : ''}`
}

export function CodeTaskLink({ taskId }: CodeTaskLinkProps): JSX.Element {
    const { searchParams } = useValues(router)
    const deepLink = taskId ? taskDeepLink(taskId, searchParams) : null
    const { status, retry } = useDesktopHandoff(deepLink)

    return (
        <DesktopHandoff
            status={status}
            onRetry={retry}
            description="This task lives in the PostHog Desktop app."
            view="code-task-link"
        />
    )
}

export default CodeTaskLink
