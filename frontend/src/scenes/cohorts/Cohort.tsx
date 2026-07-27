import { CohortEdit } from 'scenes/cohorts/CohortEdit'
import { SceneExport } from 'scenes/sceneTypes'

import { CohortType } from '~/types'

import { cohortSceneLogic } from './cohortSceneLogic'

interface CohortSceneProps {
    id?: CohortType['id']
}
export const scene: SceneExport<CohortSceneProps> = {
    component: Cohort,
    logic: cohortSceneLogic,
    paramsToProps: ({ params: { id } }) => ({
        id: id && id !== 'new' ? parseInt(id) : 'new',
    }),
}

interface CohortProps {
    id?: CohortType['id']
}

export function Cohort({ id }: CohortProps): JSX.Element {
    return <CohortEdit id={id} attachTo={cohortSceneLogic()} />
}
