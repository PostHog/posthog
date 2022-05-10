import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { useValues } from 'kea'
import { Skeleton } from 'antd'
import { frontendAppSceneLogic } from 'scenes/apps/frontendAppSceneLogic'

export function FrontendAppScene(): JSX.Element {
    const { Component, logicProps } = useValues(frontendAppSceneLogic)

    if (Component) {
        return <Component {...logicProps} />
    }
    return (
        <div style={{ marginTop: 20 }}>
            <Skeleton />
        </div>
    )
}

export const scene: SceneExport = {
    component: FrontendAppScene,
    logic: frontendAppSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id: parseInt(id) ?? 0 }),
}
