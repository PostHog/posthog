import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ExperimentStatsMethod } from '~/types'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { WebExperimentImplementationDetails } from '../WebExperimentImplementationDetails'
import { StatsMethodModal } from './StatsMethodModal'

export function SettingsTab(): JSX.Element {
    const { experiment, statsMethod, isExperimentDraft } = useValues(experimentLogic)
    const { openStatsEngineModal } = useActions(modalsLogic)

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
            {!isExperimentDraft && (
                <div>
                    <h2 className="font-semibold text-lg">Code</h2>
                    {experiment.type === 'web' ? (
                        <WebExperimentImplementationDetails experiment={experiment} />
                    ) : (
                        <ExperimentImplementationDetails experiment={experiment} />
                    )}
                </div>
            )}
        </div>
    )
}
