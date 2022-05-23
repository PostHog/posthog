import { kea, key, path, props, selectors } from 'kea'
import { cohortLogicType } from './cohortLogicType'
import { Breadcrumb, CohortType } from '~/types'
import { urls } from 'scenes/urls'
import { cohortsModel } from '~/models/cohortsModel'

export interface CohortLogicProps {
    id?: CohortType['id']
}

export const cohortLogic = kea<cohortLogicType<CohortLogicProps>>([
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
