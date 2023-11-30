import { api } from '@posthog/apps-common'
import Fuse from 'fuse.js'
import { connect, kea, path, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { cohortsModel } from '~/models/cohortsModel'
import { CohortType } from '~/types'

import { ExtendedListItem, SidebarCategory } from '../types'
import type { cohortsSidebarLogicType } from './cohortsType'
import { FuseSearchMatch } from './utils'

const fuse = new Fuse<CohortType>([], {
    keys: [{ name: 'name', weight: 2 }],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
})

export const cohortsSidebarLogic = kea<cohortsSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'cohortsSidebarLogic']),
    connect({
        values: [cohortsModel, ['cohorts', 'cohortsLoading'], sceneLogic, ['activeScene', 'sceneParams']],
        actions: [cohortsModel, ['deleteCohort']],
    }),
    selectors(({ actions }) => ({
        contents: [
            (s) => [s.relevantCohorts, s.cohortsLoading],
            (relevantCohorts, cohortsLoading) => [
                {
                    key: 'cohorts',
                    noun: 'cohort',
                    onAdd: urls.cohort('new'),
                    items: relevantCohorts.map(
                        ([cohort, matches]) =>
                            ({
                                key: cohort.id,
                                name: cohort.name,
                                url: urls.cohort(cohort.id),
                                summary: pluralize(cohort.count ?? 0, 'person', 'persons'),
                                extraContextTop: dayjs(cohort.created_at),
                                extraContextBottom: `by ${cohort.created_by?.first_name || 'unknown'}`,
                                searchMatch: matches
                                    ? {
                                          matchingFields: matches.map((match) => match.key),
                                          nameHighlightRanges: matches.find((match) => match.key === 'name')?.indices,
                                      }
                                    : null,
                                menuItems: (initiateRename) => [
                                    {
                                        items: [
                                            {
                                                onClick: initiateRename,
                                                label: 'Rename',
                                                keyboardShortcut: ['enter'],
                                            },
                                            {
                                                onClick: () => {
                                                    actions.deleteCohort(cohort)
                                                },
                                                status: 'danger',
                                                label: 'Delete cohort',
                                            },
                                        ],
                                    },
                                ],
                                onRename: async (newName) => {
                                    await api.cohorts.update(cohort.id, { name: newName })
                                    cohortsModel.actions.updateCohort({ ...cohort, name: newName })
                                },
                            } as ExtendedListItem)
                    ),
                    loading: cohortsLoading,
                } as SidebarCategory,
            ],
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams): [string, number] | null => {
                return activeScene === Scene.Cohort && sceneParams.params.id
                    ? ['cohorts', parseInt(sceneParams.params.id)]
                    : null
            },
        ],
        relevantCohorts: [
            (s) => [s.cohorts, navigation3000Logic.selectors.searchTerm],
            (cohorts, searchTerm): [CohortType, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return fuse.search(searchTerm).map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return cohorts.map((cohort) => [cohort, null])
            },
        ],
    })),
    subscriptions({
        cohorts: (cohorts) => {
            fuse.setCollection(cohorts)
        },
    }),
])
