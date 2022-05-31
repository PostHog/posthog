import './Cohort.scss'
import React from 'react'
import { cohortLogic, CohortLogicProps } from './cohortLogic'
import 'antd/lib/dropdown/style/index.css'
import { SceneExport } from 'scenes/sceneTypes'
import { CohortEdit } from 'scenes/cohorts/CohortEdit'

export const scene: SceneExport = {
    component: Cohort,
    logic: cohortLogic,
    paramsToProps: ({ params: { id } }): typeof cohortLogic['props'] => ({
        id: id && id !== 'new' ? parseInt(id) : 'new',
    }),
}

export function Cohort({ id }: CohortLogicProps = {}): JSX.Element {
    return <CohortEdit id={id} />
}
