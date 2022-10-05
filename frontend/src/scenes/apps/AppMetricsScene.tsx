import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { appMetricsSceneLogic } from 'scenes/apps/appMetricsSceneLogic'
import { Card } from 'antd'

export function AppMetrics(): JSX.Element {
    return (
        <div className="mt-4">
            <Card title="Metrics overview">
                <div>
                    <div className="card-secondary">Events delivered on first try</div>
                    <div>568,048</div>
                </div>
                <div>
                    <div className="card-secondary">Events delivered on retry</div>
                    <div>134</div>
                </div>
                <div>
                    <div className="card-secondary">Events failed</div>
                    <div>0</div>
                </div>
            </Card>
        </div>
    )
}

export const scene: SceneExport = {
    component: AppMetrics,
    logic: appMetricsSceneLogic,
    paramsToProps: ({ params: { pluginConfigId } }) => ({ pluginConfigId: parseInt(pluginConfigId) ?? 0 }),
}
