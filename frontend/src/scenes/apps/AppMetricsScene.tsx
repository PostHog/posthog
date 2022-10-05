import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { appMetricsSceneLogic } from 'scenes/apps/appMetricsSceneLogic'

export function AppMetrics(): JSX.Element {
    return <></>
}

export const scene: SceneExport = {
    component: AppMetrics,
    logic: appMetricsSceneLogic,
    paramsToProps: ({ params: { pluginConfigId } }) => ({ pluginConfigId: parseInt(pluginConfigId) ?? 0 }),
}
