import { useValues } from 'kea'

import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { urls } from 'scenes/urls'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { experimentLogic } from '../experimentLogic'

export function SettingsTab(): JSX.Element {
    const { experiment } = useValues(experimentLogic)

    const returnTo = urls.experiment(experiment.id)

    // Only show alerts section for saved experiments, as the alert relies on experiment.id for filtering
    const shouldShowSignificanceAlerts = typeof experiment.id === 'number'

    return (
        <div className="flex flex-col gap-8">
            {shouldShowSignificanceAlerts && (
                <div>
                    <h2 className="font-semibold text-lg">Notifications</h2>
                    <p className="text-muted text-xs mt-1">Get notified when a metric reaches significance.</p>
                    <LinkedHogFunctions
                        type="internal_destination"
                        subTemplateIds={['experiment-significant']}
                        forceFilterGroups={[
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
                        ]}
                        queryParams={{ returnTo }}
                    />
                </div>
            )}
        </div>
    )
}
