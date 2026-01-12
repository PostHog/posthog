import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { router } from 'kea-router'

import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'

import type { deleteFeatureFlagLogicType } from './deleteFeatureFlagLogicType'

export interface DeleteFeatureFlagForm {
    featureFlagId: number | null
    featureFlagKey: string
    deleteUsageDashboard: boolean
    hasUsageDashboard: boolean
}

const defaultFormValues: DeleteFeatureFlagForm = {
    featureFlagId: null,
    featureFlagKey: '',
    deleteUsageDashboard: false,
    hasUsageDashboard: false,
}

export const deleteFeatureFlagLogic = kea<deleteFeatureFlagLogicType>([
    path(['scenes', 'feature-flags', 'deleteFeatureFlagLogic']),
    connect({
        values: [projectLogic, ['currentProjectId']],
    }),
    actions({
        showDeleteFeatureFlagModal: (id: number, key: string, hasUsageDashboard: boolean) => ({
            id,
            key,
            hasUsageDashboard,
        }),
        hideDeleteFeatureFlagModal: true,
    }),
    reducers({
        deleteFeatureFlagModalVisible: [
            false,
            {
                showDeleteFeatureFlagModal: () => true,
                hideDeleteFeatureFlagModal: () => false,
            },
        ],
    }),
    forms(({ values, actions }) => ({
        deleteFeatureFlag: {
            defaults: defaultFormValues,
            errors: () => ({}),
            submit: async ({ featureFlagId, featureFlagKey, deleteUsageDashboard }) => {
                await deleteWithUndo({
                    endpoint: `projects/${values.currentProjectId}/feature_flags`,
                    object: {
                        id: featureFlagId,
                        name: featureFlagKey,
                        _should_delete_usage_dashboard: deleteUsageDashboard,
                    },
                    callback: (undo) => {
                        featureFlagsLogic.actions.loadFeatureFlags()
                        if (undo) {
                            refreshTreeItem('feature_flag', String(featureFlagId))
                        } else {
                            deleteFromTree('feature_flag', String(featureFlagId))
                        }
                    },
                })
                actions.hideDeleteFeatureFlagModal()
                router.actions.push(urls.featureFlags())
            },
        },
    })),
    listeners(({ actions }) => ({
        showDeleteFeatureFlagModal: ({ id, key, hasUsageDashboard }) => {
            actions.setDeleteFeatureFlagValues({
                featureFlagId: id,
                featureFlagKey: key,
                hasUsageDashboard,
                deleteUsageDashboard: false,
            })
        },
        hideDeleteFeatureFlagModal: () => {
            actions.resetDeleteFeatureFlag()
        },
    })),
])
