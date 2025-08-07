import { kea, key, props, selectors, path } from 'kea'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { CohortLogicProps } from './cohortEditLogic'
import type { cohortsSceneLogicType } from './cohortsSceneLogicType'

export const cohortsSceneLogic = kea<cohortsSceneLogicType>([
    path(['scenes', 'cohorts', 'cohortsSceneLogic']),
    props({} as CohortLogicProps),
    key((props) => props.id || 'new'),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
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
                ]
            },
        ],
    }),
])
