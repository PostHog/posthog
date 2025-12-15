import { SceneExport } from 'scenes/sceneTypes'

import { Viz } from './Viz'
import { VizLogicProps, vizLogic } from './vizLogic'

export const scene: SceneExport<VizLogicProps> = {
    component: VizScene,
    logic: vizLogic,
    paramsToProps: ({ params: { brand } }) => ({
        brand: brand || 'posthog',
    }),
}

export function VizScene({ brand }: VizLogicProps): JSX.Element {
    return <Viz brand={brand} />
}

export default VizScene
