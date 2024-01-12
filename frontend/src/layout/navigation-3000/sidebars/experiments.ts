import Fuse from 'fuse.js'
import { connect, kea, path, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { dayjs } from 'lib/dayjs'
import { experimentsLogic, getExperimentStatus } from 'scenes/experiments/experimentsLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Experiment, ProgressStatus } from '~/types'

import { navigation3000Logic } from '../navigationLogic'
import { ExtendedListItem, SidebarCategory } from '../types'
import type { experimentsSidebarLogicType } from './experimentsType'
import { FuseSearchMatch } from './utils'

const fuse = new Fuse<Experiment>([], {
    keys: [{ name: 'name', weight: 2 }, 'description'],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
})

const EXPERIMENT_STATUS_TO_RIBBON_STATUS = { draft: 'muted', running: 'success', complete: 'completion' }

export const experimentsSidebarLogic = kea<experimentsSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'experimentsSidebarLogic']),
    connect({
        values: [experimentsLogic, ['experiments', 'experimentsLoading'], sceneLogic, ['activeScene', 'sceneParams']],
        actions: [experimentsLogic, ['loadExperiments', 'deleteExperiment']],
    }),
    selectors(({ actions }) => ({
        contents: [
            (s) => [s.relevantExperiments, s.experimentsLoading],
            (relevantExperiments, experimentsLoading) => [
                {
                    key: 'experiments',
                    noun: 'experiment',
                    loading: experimentsLoading,
                    items: relevantExperiments.map(([experiment, matches]) => {
                        const experimentStatus = getExperimentStatus(experiment)
                        return {
                            key: experiment.id,
                            name: experiment.name,
                            summary:
                                experimentStatus === ProgressStatus.Draft
                                    ? 'Draft'
                                    : experimentStatus === ProgressStatus.Complete
                                    ? `Completed ${dayjs(experiment.start_date).fromNow()}`
                                    : `Running for ${dayjs(experiment.start_date).fromNow(true)} now`,
                            extraContextTop: dayjs(experiment.created_at),
                            extraContextBottom: `by ${experiment.created_by?.first_name || 'unknown'}`,
                            url: urls.experiment(experiment.id),
                            searchMatch: matches
                                ? {
                                      matchingFields: matches.map((match) => match.key),
                                      nameHighlightRanges: matches.find((match) => match.key === 'name')?.indices,
                                  }
                                : null,
                            marker: {
                                type: 'ribbon',
                                status: EXPERIMENT_STATUS_TO_RIBBON_STATUS[experimentStatus],
                            },
                            menuItems: [
                                {
                                    items: [
                                        {
                                            label: 'Delete experiment',
                                            onClick: () => actions.deleteExperiment(experiment.id as number),
                                            status: 'danger',
                                        },
                                    ],
                                },
                            ],
                        } as ExtendedListItem
                    }),
                    onAdd: urls.experiment('new'),
                } as SidebarCategory,
            ],
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams): [string, number] | null => {
                return activeScene === Scene.Experiment && sceneParams.params.id
                    ? ['experiments', parseInt(sceneParams.params.id)]
                    : null
            },
        ],
        relevantExperiments: [
            (s) => [s.experiments, navigation3000Logic.selectors.searchTerm],
            (experiments, searchTerm): [Experiment, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return fuse.search(searchTerm).map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return experiments.map((experiment) => [experiment, null])
            },
        ],
    })),
    subscriptions({
        experiments: (experiments) => {
            fuse.setCollection(experiments)
        },
    }),
])
