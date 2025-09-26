import { actions, connect, isBreakpoint, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import type { Experiment } from '~/types'

import { NEW_EXPERIMENT } from '../constants'
import type { createExperimentLogicType } from './createExperimentLogicType'

export const createExperimentLogic = kea<createExperimentLogicType>({
    props: () => ({}),
    path: () => ['scenes', 'experiments', 'create', 'createExperimentLogic'],
    connect: () => ({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [eventUsageLogic, ['reportExperimentCreated'], featureFlagsLogic, ['updateFlag']],
    }),
    forms: () => ({
        experiment: {
            options: { showErrorsOnTouch: true },
            defaults: { ...NEW_EXPERIMENT } as Experiment,
            errors: ({ name, description }: Experiment) => ({
                name: !name ? 'Name is required' : undefined,
                description: !description ? 'Hypothesis is required' : undefined,
            }),
            submit: () => {},
        },
    }),
    actions: () => ({
        setExperiment: (experiment: Experiment) => ({ experiment }),
        createExperiment: () => ({}),
    }),
    reducers: () => ({
        experiment: [
            { ...NEW_EXPERIMENT } as Experiment,
            {
                setExperiment: (_, { experiment }) => experiment,
            },
        ],
    }),
    listeners: ({ values }) => ({
        setExperiment: ({ experiment }: { experiment: Experiment }) => {
            console.log('setExperiment', experiment)
            //actions.setExperiment(experiment)
        },
        createExperiment: async () => {
            console.log('createExperiment', values.experiment)
            //actions.reportExperimentCreated(values.experiment)
        },
    }),
})
