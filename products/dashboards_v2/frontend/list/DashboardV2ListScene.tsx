import { SceneExport } from 'scenes/sceneTypes'

import { DashboardsV2Gate } from '../DashboardsV2Gate'
import { DashboardV2List } from './DashboardV2List'
import { dashboardV2ListLogic } from './dashboardV2ListLogic'

export const scene: SceneExport = {
    component: DashboardV2ListScene,
    logic: dashboardV2ListLogic,
}

export function DashboardV2ListScene(): JSX.Element {
    return (
        <DashboardsV2Gate>
            <DashboardV2List />
        </DashboardsV2Gate>
    )
}
