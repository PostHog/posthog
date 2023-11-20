import { kea, key, path, props, selectors } from 'kea'
import { Breadcrumb } from '~/types'
import { urls } from 'scenes/urls'
import { cohortsModel } from '~/models/cohortsModel'
import { CohortLogicProps } from './cohortEditLogic'

import type { cohortSceneLogicType } from './cohortSceneLogicType'
import { Scene } from 'scenes/sceneTypes'

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
                        key: Scene.PersonsManagement,
                        name: 'People',
                        path: urls.persons(),
                    },
                    {
                        key: 'cohorts',
                        name: 'Cohorts',
                        path: urls.cohorts(),
                    },
                    {
                        key: cohortId || 'loading',
                        name: cohortId && cohortId !== 'new' ? cohortsById[cohortId]?.name || 'Untitled' : 'Untitled',
                    },
                ]
            },
        ],
    }),
])
