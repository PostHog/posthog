import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { useValues } from 'kea'
import { Skeleton } from 'antd'
import { frontendAppSceneLogic } from 'scenes/apps/frontendAppSceneLogic'
import { PageHeader } from 'lib/components/PageHeader'

export function FrontendAppScene(): JSX.Element {
    const { Component, logicProps, breadcrumbs } = useValues(frontendAppSceneLogic)

    return (
        <>
            <PageHeader
                title={
                    (breadcrumbs.length > 0 && breadcrumbs[breadcrumbs.length - 1]?.name) ||
                    logicProps?.name ||
                    'App Loading...'
                }
            />
            {Component ? <Component {...logicProps} /> : <Skeleton />}
        </>
    )
}

export const scene: SceneExport = {
    component: FrontendAppScene,
    logic: frontendAppSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id: parseInt(id) ?? 0 }),
}
