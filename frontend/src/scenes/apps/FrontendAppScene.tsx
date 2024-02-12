import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { frontendAppSceneLogic } from 'scenes/apps/frontendAppSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'

export function FrontendAppScene(): JSX.Element {
    const { Component, appConfig } = useValues(frontendAppSceneLogic)

    return (
        <>
            <PageHeader />
            {Component ? <Component {...appConfig} /> : <SpinnerOverlay />}
        </>
    )
}

export const scene: SceneExport = {
    component: FrontendAppScene,
    logic: frontendAppSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id: parseInt(id) ?? 0 }),
}
