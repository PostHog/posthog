import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode, useEffect } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { ClassicEmbedContext, isClassicEmbedPath } from './classicEmbedContext'

export function ClassicEmbed({
    context,
    children,
}: {
    context: ClassicEmbedContext
    children: ReactNode
}): JSX.Element {
    const { location } = useValues(router)
    const { activeSceneId } = useValues(sceneLogic)
    const { user } = useValues(userLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { activePanelIdentifier } = useValues(panelLayoutLogic)
    const { clearActivePanelIdentifier, showLayoutPanel } = useActions(panelLayoutLogic)
    const accountId = user?.uuid
    const allowed = isClassicEmbedPath(location.pathname, context.projectId) && activeSceneId !== Scene.Max
    const ready = allowed && String(currentTeamId) === context.projectId && !!activeSceneId

    useEffect(() => {
        if (activePanelIdentifier === 'Chat') {
            clearActivePanelIdentifier()
            showLayoutPanel(false)
        }
    }, [activePanelIdentifier, clearActivePanelIdentifier, showLayoutPanel])

    useEffect(() => {
        const url = new URL(window.location.href)
        url.searchParams.set('__desktop_classic', '1')
        url.searchParams.set('__desktop_parent_origin', context.parentOrigin)
        window.history.replaceState(window.history.state, '', url.href)
    }, [context.parentOrigin, location.pathname, location.search, location.hash])

    useEffect(() => {
        const report = (): void => {
            window.parent.postMessage(
                {
                    type: 'posthog:classic:status',
                    status: !allowed ? 'error' : ready && accountId ? 'ready' : 'loading',
                    accountId,
                    projectId: String(currentTeamId),
                },
                context.parentOrigin
            )
        }
        const receive = (event: MessageEvent): void => {
            if (
                event.source === window.parent &&
                event.origin === context.parentOrigin &&
                event.data?.type === 'posthog:classic:ping'
            ) {
                report()
            }
        }
        const leaving = (): void => {
            window.parent.postMessage({ type: 'posthog:classic:status', status: 'loading' }, context.parentOrigin)
        }
        window.addEventListener('message', receive)
        window.addEventListener('pagehide', leaving)
        report()
        return () => {
            window.removeEventListener('message', receive)
            window.removeEventListener('pagehide', leaving)
        }
    }, [allowed, ready, accountId, currentTeamId, context])

    return allowed ? (
        <>{children}</>
    ) : (
        <LemonButton to={`/project/${context.projectId}/dashboard`}>Return to Classic</LemonButton>
    )
}
