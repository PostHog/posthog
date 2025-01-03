import { actions, connect, kea, listeners, path, props } from 'kea'
import { router } from 'kea-router'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { FeatureType } from '~/types'

import type { featureManagementDetailLogicType } from './featureManagementDetailLogicType'
import { featureManagementLogic } from './featureManagementLogic'

export const featureManagementDetailLogic = kea<featureManagementDetailLogicType>([
    props({}),
    path(['scenes', 'features', 'featureManagementDetailLogic']),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            projectLogic,
            ['currentProjectId'],
            featureManagementLogic,
            ['activeFeatureId', 'activeFeature'],
        ],
        actions: [featureManagementLogic, ['loadFeatures']],
    }),
    actions({
        deleteFeature: (feature: FeatureType) => ({ feature }),
    }),
    listeners(({ actions, values }) => ({
        deleteFeature: async ({ feature }) => {
            await deleteWithUndo({
                endpoint: `projects/${values.currentProjectId}/features`,
                object: { id: feature.id, name: feature.name },
                callback: () => {
                    actions.loadFeatures()
                    router.actions.push(urls.featureManagement())
                },
            })
        },
    })),
])
