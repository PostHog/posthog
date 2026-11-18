import { useValues } from 'kea'

import { urls } from 'scenes/urls'

import { CyclotronJobFiltersType, HogFunctionSubTemplateIdType, PropertyFilterType, PropertyOperator } from '~/types'

import { experimentLogic } from '../experimentLogic'

export const NOTIFICATIONS_TITLE = 'Notifications'
export const NOTIFICATIONS_DESCRIPTION = 'Get notified when a metric reaches significance.'
export const EXPERIMENT_NOTIFICATION_SUB_TEMPLATES: HogFunctionSubTemplateIdType[] = ['experiment-significant']

export interface ExperimentNotificationsConfig {
    shouldShow: boolean
    forceFilterGroups: CyclotronJobFiltersType[]
    returnTo: string
}

export function useExperimentNotificationsConfig(): ExperimentNotificationsConfig {
    const { experiment } = useValues(experimentLogic)
    return {
        // Only show alerts section for saved experiments, as the alert relies on experiment.id for filtering
        shouldShow: typeof experiment.id === 'number',
        forceFilterGroups: [
            {
                events: [{ id: '$experiment_metric_significant', type: 'events' }],
                properties: [
                    {
                        key: 'experiment_id',
                        type: PropertyFilterType.Event,
                        value: experiment.id,
                        operator: PropertyOperator.Exact,
                    },
                ],
            },
        ],
        returnTo: urls.experiment(experiment.id),
    }
}
