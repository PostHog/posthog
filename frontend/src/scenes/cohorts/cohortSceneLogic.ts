import { kea, path, props, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { cohortsModel } from '~/models/cohortsModel'
import { ActivityScope, Breadcrumb, ProjectTreeRef } from '~/types'

import { CohortLogicProps } from './cohortEditLogic'
import type { cohortSceneLogicType } from './cohortSceneLogicType'

export const cohortSceneLogic = kea<cohortSceneLogicType>([
    props({} as CohortLogicProps),
    tabAwareScene(),
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
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [(_, props: CohortLogicProps) => props.id],
            (id: CohortLogicProps['id']): SidePanelSceneContext | null => {
                return id && id !== 'new'
                    ? {
                          activity_scope: ActivityScope.COHORT,
                          activity_item_id: `${id}`,
                      }
                    : null
            },
        ],
        projectTreeRef: [
            () => [(_, props: CohortLogicProps) => props.id],
            (id): ProjectTreeRef => ({ type: 'cohort', ref: id === 'new' ? null : String(id) }),
        ],
    }),
])
