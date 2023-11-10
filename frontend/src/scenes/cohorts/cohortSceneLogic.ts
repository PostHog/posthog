import { kea, key, path, props, selectors } from 'kea'
import { Breadcrumb } from '~/types'
import { urls } from 'scenes/urls'
import { cohortsModel } from '~/models/cohortsModel'
import { CohortLogicProps } from './cohortEditLogic'

import type { cohortSceneLogicType } from './cohortSceneLogicType'

export const cohortSceneLogic = kea<cohortSceneLogicType>([
    props({} as CohortLogicProps),
    key((props) => props.id || 'new'),
    path(['scenes', 'cohorts', 'cohortLogic']),

    selectors({
        breadcrumbs: [
            () => [cohortsModel.selectors.cohortsById, (_, props) => props.id],
            (cohortsById, cohortId): Breadcrumb[] => {
                return [
                    {
                        name: 'Cohorts',
                        path: urls.cohorts(),
                    },
                    {
                        name: cohortId !== 'new' ? cohortsById[cohortId]?.name || 'Untitled' : 'Untitled',
                    },
                ]
            },
        ],
    }),
])
