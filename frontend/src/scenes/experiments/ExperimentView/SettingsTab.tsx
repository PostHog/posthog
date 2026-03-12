import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'

import { ExperimentStatsMethod } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { StatsMethodModal } from './StatsMethodModal'

export function SettingsTab(): JSX.Element {
    const { experiment, statsMethod } = useValues(experimentLogic)
    const { openStatsEngineModal } = useActions(modalsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const isBayesian = statsMethod === ExperimentStatsMethod.Bayesian

    const confidenceDisplay = isBayesian
        ? `${((experiment.stats_config?.bayesian?.ci_level ?? 0.95) * 100).toFixed(0)}%`
        : `${((1 - (experiment.stats_config?.frequentist?.alpha ?? 0.05)) * 100).toFixed(0)}%`

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
            {featureFlags[FEATURE_FLAGS.EXPERIMENT_SIGNIFICANCE_ALERTS] && (
                <div>
                    <h2 className="font-semibold text-lg">Notifications</h2>
                    <p>Get notified when a metric reaches significance.</p>
                    <LinkedHogFunctions type="internal_destination" subTemplateIds={['experiment-significant']} />
                </div>
            )}
        </div>
    )
}
