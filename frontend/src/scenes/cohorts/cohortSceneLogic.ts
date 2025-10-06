import { kea, key, path, props, selectors } from 'kea'

import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { Breadcrumb, ProjectTreeRef } from '~/types'

import { CohortLogicProps } from './cohortEditLogic'
import type { cohortSceneLogicType } from './cohortSceneLogicType'

export const cohortSceneLogic = kea<cohortSceneLogicType>([
    props({} as CohortLogicProps),
    key((props) => props.id || 'new'),
    path(['scenes', 'cohorts', 'cohortLogic']),

    selectors({
        breadcrumbs: [
            () => [cohortsModel.selectors.cohortsById, (_, props) => props.id as CohortLogicProps['id']],
            (cohortsById, cohortId): Breadcrumb[] => {
                return [
                    {
                        key: 'cohorts',
                        name: 'Cohorts',
                        path: urls.cohorts(),
                        iconType: 'cohort',
                    },
                    {
                        key: [Scene.Cohort, cohortId || 'loading'],
                        name: cohortId && cohortId !== 'new' ? cohortsById[cohortId]?.name || 'Untitled' : 'Untitled',
                        iconType: 'cohort',
                    },
                ]
            },
        ],
        projectTreeRef: [
            () => [(_, props: CohortLogicProps) => props.id],
            (id): ProjectTreeRef => ({ type: 'cohort', ref: id === 'new' ? null : String(id) }),
        ],
    }),
])
