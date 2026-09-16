import { useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode, RefObject, useEffect } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ClassicEmbedContext, isClassicEmbedPath } from './classicEmbed'

export function ClassicEmbed({
    context,
    children,
    mainRef,
}: {
    context: ClassicEmbedContext
    children: ReactNode
    mainRef: RefObject<HTMLElement>
}): JSX.Element {
    const { location, searchParams, hashParams } = useValues(router)
    const { activeSceneId } = useValues(sceneLogic)
    const { user } = useValues(userLogic)
    const { currentTeamId } = useValues(teamLogic)
    const accountId = user?.uuid
    const allowed = isClassicEmbedPath(location.pathname, context.projectId)
    const ready =
        allowed &&
        String(currentTeamId) === context.projectId &&
        [Scene.Dashboards, Scene.Dashboard, Scene.Insight].includes(activeSceneId as Scene)

    useEffect(() => {
        if (searchParams.__desktop_classic !== '1' || searchParams.__desktop_parent_origin !== context.parentOrigin) {
            router.actions.replace(
                location.pathname,
                { ...searchParams, __desktop_classic: '1', __desktop_parent_origin: context.parentOrigin },
                hashParams
            )
        }
    }, [context.parentOrigin, location.pathname, searchParams, hashParams])

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

    return (
        <div className="Navigation3000 flex-col">
            <main
                ref={mainRef}
                id="main-content"
                tabIndex={0}
                className="@container/main-content p-4"
                aria-label="Classic web page"
            >
                {allowed ? (
                    children
                ) : (
                    <LemonButton to={`/project/${context.projectId}/dashboard`}>Return to dashboards</LemonButton>
                )}
            </main>
        </div>
    )
}
