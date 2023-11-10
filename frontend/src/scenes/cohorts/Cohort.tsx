import { cohortSceneLogic } from './cohortSceneLogic'
import 'antd/lib/dropdown/style/index.css'
import { SceneExport } from 'scenes/sceneTypes'
import { CohortEdit } from 'scenes/cohorts/CohortEdit'
import { CohortLogicProps } from './cohortEditLogic'

export const scene: SceneExport = {
    component: Cohort,
    logic: cohortSceneLogic,
    paramsToProps: ({ params: { id } }): (typeof cohortSceneLogic)['props'] => ({
        id: id && id !== 'new' ? parseInt(id) : 'new',
    }),
}

export function Cohort({ id }: CohortLogicProps = {}): JSX.Element {
    return <CohortEdit id={id} />
}
