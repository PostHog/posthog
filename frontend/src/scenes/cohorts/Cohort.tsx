import 'antd/lib/dropdown/style/index.css'

import { BindLogic } from 'kea'
import { CohortEdit } from 'scenes/cohorts/CohortEdit'
import { SceneExport } from 'scenes/sceneTypes'

import { cohortEditLogic, CohortLogicProps } from './cohortEditLogic'
import { cohortSceneLogic } from './cohortSceneLogic'

export const scene: SceneExport = {
    component: Cohort,
    logic: cohortSceneLogic,
    paramsToProps: ({ params: { id } }): (typeof cohortSceneLogic)['props'] => ({
        id: id && id !== 'new' ? parseInt(id) : 'new',
    }),
}

export function Cohort({ id }: CohortLogicProps = {}): JSX.Element {
    return (
        <BindLogic logic={cohortEditLogic} props={{ id }}>
            <CohortEdit />
        </BindLogic>
    )
}
