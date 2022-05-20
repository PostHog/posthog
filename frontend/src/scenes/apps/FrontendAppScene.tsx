import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { useValues } from 'kea'
import { Skeleton } from 'antd'
import { frontendAppSceneLogic } from 'scenes/apps/frontendAppSceneLogic'
import { PageHeader } from 'lib/components/PageHeader'

export function FrontendAppScene(): JSX.Element {
    const { Component, appConfig, breadcrumbs } = useValues(frontendAppSceneLogic)

    return (
        <>
            <PageHeader
                title={
                    (breadcrumbs.length > 0 && breadcrumbs[breadcrumbs.length - 1]?.name) ||
                    appConfig?.name ||
                    'App Loading...'
                }
            />
            {Component ? <Component {...appConfig} /> : <Skeleton />}
        </>
    )
}

export const scene: SceneExport = {
    component: FrontendAppScene,
    logic: frontendAppSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id: parseInt(id) ?? 0 }),
}
