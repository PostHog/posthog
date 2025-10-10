import { actions, connect, kea, key, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import type { Experiment, FeatureFlagFilters } from '~/types'
import { ProductKey } from '~/types'

import { NEW_EXPERIMENT } from '../constants'
import type { createExperimentLogicType } from './createExperimentLogicType'

export const createExperimentLogic = kea<createExperimentLogicType>([
    key(() => 'create-experiment'),
    path(['scenes', 'experiments', 'create', 'createExperimentLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [
            eventUsageLogic,
            ['reportExperimentCreated'],
            featureFlagsLogic,
            ['updateFlag'],
            teamLogic,
            ['addProductIntent'],
        ],
    })),
    forms(({ actions }) => ({
        experiment: {
            options: { showErrorsOnTouch: true },
            defaults: { ...NEW_EXPERIMENT } as Experiment,
            errors: ({ name, description }: Experiment) => ({
                name: !name ? 'Name is required' : undefined,
                description: !description ? 'Hypothesis is required' : undefined,
            }),
            submit: () => {
                actions.createExperiment()
            },
        },
    })),
    actions(() => ({
        setExperiment: (experiment: Experiment) => ({ experiment }),
        createExperiment: () => ({}),
        createExperimentSuccess: true,
    })),
    reducers(() => ({
        experiment: [
            { ...NEW_EXPERIMENT } as Experiment & { feature_flag_filters?: FeatureFlagFilters },
            { persist: true },
            {
                setExperiment: (_, { experiment }) => experiment,
                updateFeatureFlagKey: (state, { key }) => ({ ...state, feature_flag_key: key }),
                resetExperiment: () => ({ ...NEW_EXPERIMENT }),
            },
        ],
    })),
    listeners(({ values, actions }) => ({
        setExperiment: () => {},
        setExperimentValue: () => {},
        createExperiment: async () => {
            const response = (await api.create(`api/projects/@current/experiments`, values.experiment)) as Experiment

            if (response.id) {
                // Report analytics
                actions.reportExperimentCreated(response)
                actions.addProductIntent({
                    product_type: ProductKey.EXPERIMENTS,
                    intent_context: ProductIntentContext.EXPERIMENT_CREATED,
                })

                // Signal successful creation (triggers Hogfetti in component)
                actions.createExperimentSuccess()

                // Refresh tree navigation
                refreshTreeItem('experiment', String(response.id))
                if (response.feature_flag?.id) {
                    refreshTreeItem('feature_flag', String(response.feature_flag.id))
                }

                // Show success toast
                lemonToast.success('Experiment created successfully!', {
                    button: {
                        label: 'View it',
                        action: () => {
                            router.actions.push(urls.experiment(response.id))
                        },
                    },
                })

                // Reset form for next experiment (clear persisted state)
                actions.resetExperiment()

                // Navigate to experiment page
                router.actions.push(urls.experiment(response.id))
            }
        },
    })),
])
