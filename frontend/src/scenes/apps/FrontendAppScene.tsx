import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { useValues } from 'kea'
import { urls } from 'scenes/urls'
import { Skeleton } from 'antd'
import { frontendAppSceneLogic } from 'scenes/apps/frontendAppSceneLogic'

export function FrontendAppScene(props: Record<string, any> = {}): JSX.Element {
    const { Component } = useValues(frontendAppSceneLogic)
    if (Component) {
        return <Component {...props} />
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
    paramsToProps: ({ params: { id } }) => ({ id: parseInt(id) ?? 0, url: id ? urls.frontendApp(id) : '' }),
}
