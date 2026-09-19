import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SceneExport } from 'scenes/sceneTypes'

import { DesktopBridgeBody } from './DesktopBridgeBody'
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

    useEffect(() => {
        if (deepLink) {
            window.location.href = deepLink
        }
    }, [deepLink])

    return (
        <BridgePage view="code-task-link">
            <DesktopBridgeBody subject="This task" deepLink={deepLink} />
        </BridgePage>
    )
}

export default CodeTaskLink
