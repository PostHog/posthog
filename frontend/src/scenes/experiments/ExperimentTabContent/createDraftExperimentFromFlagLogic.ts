import { actions, connect, kea, listeners, path, props, reducers } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { Experiment } from '~/types'

import type { createDraftExperimentFromFlagLogicType } from './createDraftExperimentFromFlagLogicType'

export interface CreateDraftExperimentFromFlagLogicProps {
    featureFlagKey: string
}

export const createDraftExperimentFromFlagLogic = kea<createDraftExperimentFromFlagLogicType>([
    path(['scenes', 'experiments', 'ExperimentTabContent', 'createDraftExperimentFromFlagLogic']),
    props({} as CreateDraftExperimentFromFlagLogicProps),

    connect({
        actions: [eventUsageLogic, ['reportExperimentCreated']],
        values: [teamLogic, ['currentProjectId']],
    }),

    actions({
        setExperimentName: (name: string) => ({ name }),
        setExperimentDescription: (description: string) => ({ description }),
        createDraftExperiment: true,
        createDraftExperimentSuccess: (experiment: Experiment) => ({ experiment }),
        createDraftExperimentFailure: (error: string) => ({ error }),
    }),

    reducers({
        experimentName: ['', { setExperimentName: (_, { name }) => name }],
        experimentDescription: ['', { setExperimentDescription: (_, { description }) => description }],
        isLoading: [
            false,
            {
                createDraftExperiment: () => true,
                createDraftExperimentSuccess: () => false,
                createDraftExperimentFailure: () => false,
            },
        ],
        error: [
            null as string | null,
            {
                createDraftExperiment: () => null,
                createDraftExperimentFailure: (_, { error }) => error,
                setExperimentName: () => null,
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        createDraftExperiment: async () => {
            const name = values.experimentName.trim()

            if (!name) {
                actions.createDraftExperimentFailure('Experiment name is required')
                return
            }

            // No flag config in the payload: the flag already exists, so the experiment links
            // to it as-is (its variants carry over) and explicit config would be rejected.
            const payload = {
                name,
                description: values.experimentDescription.trim() || '',
                type: 'product',
                feature_flag_key: props.featureFlagKey,
                exposure_criteria: {
                    filterTestAccounts: true,
                },
                metrics: [],
                metrics_secondary: [],
                start_date: null,
            }

            try {
                const experiment: Experiment = await api.create(
                    `api/projects/${values.currentProjectId}/experiments`,
                    payload
                )
                actions.createDraftExperimentSuccess(experiment)
            } catch (error: any) {
                const errorMessage = error?.detail || 'Failed to create experiment'
                actions.createDraftExperimentFailure(errorMessage)
            }
        },

        createDraftExperimentSuccess: ({ experiment }) => {
            lemonToast.success('Draft experiment created')
            router.actions.push(urls.experiment(experiment.id))
        },

        createDraftExperimentFailure: ({ error }) => {
            lemonToast.error(`Failed to create experiment: ${error}`)
        },
    })),
])
