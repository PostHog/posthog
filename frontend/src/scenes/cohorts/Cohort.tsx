import { CohortEdit } from 'scenes/cohorts/CohortEdit'
import { SceneExport } from 'scenes/sceneTypes'

import { CohortLogicProps } from './cohortEditLogic'
import { cohortSceneLogic } from './cohortSceneLogic'

export const scene: SceneExport<CohortLogicProps> = {
    component: Cohort,
    logic: cohortSceneLogic,
    paramsToProps: ({ params: { id } }) => ({
        id: id && id !== 'new' ? parseInt(id) : 'new',
    }),
}

export function Cohort({ id }: CohortLogicProps): JSX.Element {
    return <CohortEdit id={id} />
}
