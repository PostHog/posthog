import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { urls } from 'scenes/urls'

import { ExperimentStatsMethod, PropertyFilterType, PropertyOperator } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { StatsMethodModal } from './StatsMethodModal'

export function SettingsTab(): JSX.Element {
    const { experiment, statsMethod } = useValues(experimentLogic)
    const { updateExperiment } = useActions(experimentLogic)
    const { openStatsEngineModal } = useActions(modalsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const showMaturedUsersOption = useFeatureFlag('EXPERIMENTS_MATURED_USERS_FILTER')

    const isBayesian = statsMethod === ExperimentStatsMethod.Bayesian

    const confidenceDisplay = isBayesian
        ? `${((experiment.stats_config?.bayesian?.ci_level ?? 0.95) * 100).toFixed(0)}%`
        : `${((1 - (experiment.stats_config?.frequentist?.alpha ?? 0.05)) * 100).toFixed(0)}%`

    const returnTo = urls.experiment(experiment.id)

    // Only show alerts section for saved experiments, as the alert relies on experiment.id for filtering
    const shouldShowSignificanceAlerts =
        featureFlags[FEATURE_FLAGS.EXPERIMENT_SIGNIFICANCE_ALERTS] && typeof experiment.id === 'number'

    return (
        <div className="flex flex-col gap-8">
            <div>
                <h2 className="font-semibold text-lg">Statistics</h2>
                <div className="flex items-center gap-2">
                    <span>
                        {isBayesian ? 'Bayesian' : 'Frequentist'} / {confidenceDisplay}
                    </span>
                    <LemonButton type="secondary" size="xsmall" icon={<IconPencil />} onClick={openStatsEngineModal} />
                </div>
                <StatsMethodModal />
            </div>
            {showMaturedUsersOption && (
                <div>
                    <h2 className="font-semibold text-lg">Conversion windows</h2>
                    <div className="flex items-center gap-2">
                        <LemonCheckbox
                            label="Require completed conversion window"
                            checked={experiment.only_count_matured_users ?? false}
                            onChange={(checked) => {
                                updateExperiment({ only_count_matured_users: checked })
                            }}
                        />
                    </div>
                    <p className="text-muted text-xs mt-1">
                        Only count participants whose full conversion window has elapsed. Applies to metrics with a
                        custom time window.
                    </p>
                </div>
            )}
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
