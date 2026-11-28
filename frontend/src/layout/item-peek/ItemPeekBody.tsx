import { BindLogic, useValues } from 'kea'

import { Empty, EmptyDescription, EmptyHeader, EmptyTitle, Spinner } from '@posthog/quill'

import { userLogic } from 'scenes/userLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { ScenePeekContext } from '~/layout/scenes/components/scenePeekContext'

import { itemPeekLogic } from './itemPeekLogic'

export function ItemPeekBody(): JSX.Element {
    const { target, loadedScene, peekProps, failedSceneId } = useValues(itemPeekLogic)
    const { user } = useValues(userLogic)

    if (target && failedSceneId === target.sceneId) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyTitle>This page can't open here</EmptyTitle>
                    <EmptyDescription>Select View to open it in full.</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    if (!target || !loadedScene || !peekProps) {
        return (
            <div className="flex flex-1 items-center justify-center py-8" aria-busy="true">
                <Spinner />
            </div>
        )
    }

    const { component: SceneComponent, logic } = loadedScene.scene
    const sceneNode = <SceneComponent user={user} {...target.sceneParams.params} />

    return (
        <ErrorBoundary key={target.path} exceptionProps={{ feature: `item-peek-${target.sceneId}` }}>
            <ScenePeekContext.Provider value={true}>
                {logic ? (
                    <BindLogic logic={logic} props={peekProps}>
                        {sceneNode}
                    </BindLogic>
                ) : (
                    sceneNode
                )}
            </ScenePeekContext.Provider>
        </ErrorBoundary>
    )
}
