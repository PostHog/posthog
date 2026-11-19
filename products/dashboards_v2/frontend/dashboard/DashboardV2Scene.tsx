import { BindLogic } from 'kea'

import { SceneExport } from 'scenes/sceneTypes'

import { DashboardsV2Gate } from '../DashboardsV2Gate'
import { DashboardV2LogicProps, dashboardV2Logic } from './dashboardV2Logic'
import { DashboardV2View } from './DashboardV2View'

export const scene: SceneExport<DashboardV2LogicProps> = {
    component: DashboardV2Scene,
    logic: dashboardV2Logic,
    paramsToProps: ({ params: { uid } }) => ({ uid }),
}

export function DashboardV2Scene({ uid }: DashboardV2LogicProps): JSX.Element {
    return (
        <DashboardsV2Gate>
            <BindLogic logic={dashboardV2Logic} props={{ uid }}>
                <DashboardV2View />
            </BindLogic>
        </DashboardsV2Gate>
    )
}
