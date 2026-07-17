import { CohortEdit } from 'scenes/cohorts/CohortEdit'
import { SceneExport } from 'scenes/sceneTypes'

import { CohortType } from '~/types'

import { cohortSceneLogic } from './cohortSceneLogic'

interface CohortSceneProps {
    id?: CohortType['id']
    tabId?: string
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
    tabId?: string
}

export function Cohort({ id, tabId }: CohortProps): JSX.Element {
    if (!tabId) {
        throw new Error('Cohort must receive a tabId prop')
    }
    return <CohortEdit id={id} attachTo={cohortSceneLogic({ tabId })} tabId={tabId} />
}
