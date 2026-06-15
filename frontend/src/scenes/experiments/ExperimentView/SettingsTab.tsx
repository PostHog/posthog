import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSelect, LemonTag, Link } from '@posthog/lemon-ui'

import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { experimentsConfigLogic } from 'scenes/settings/environment/experimentsConfigLogic'
import { urls } from 'scenes/urls'

import { ExperimentStatsMethod, PropertyFilterType, PropertyOperator } from '~/types'

import { DEFAULT_LOOKBACK_DAYS } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { getCupedSelection, resolveCupedEnabled, resolveCupedLookbackDays } from './cuped'
import { CupedModal } from './CupedModal'
import { resolveSequentialEnabled } from './sequential'
import { StatsMethodModal } from './StatsMethodModal'

export function SettingsTab(): JSX.Element {
    const { experiment, statsMethod, variants } = useValues(experimentLogic)
    const { updateExperimentSettings } = useActions(experimentLogic)
    const { openStatsEngineModal, openCupedModal } = useActions(modalsLogic)
    const { experimentsConfig } = useValues(experimentsConfigLogic)

    const isBayesian = statsMethod === ExperimentStatsMethod.Bayesian

    const confidenceDisplay = isBayesian
        ? `${((experiment.stats_config?.bayesian?.ci_level ?? 0.95) * 100).toFixed(0)}%`
        : `${((1 - (experiment.stats_config?.frequentist?.alpha ?? 0.05)) * 100).toFixed(0)}%`

    const teamDefaultCupedEnabled = experimentsConfig?.default_cuped_enabled ?? false
    const teamDefaultCupedLookbackDays = experimentsConfig?.default_cuped_lookback_days ?? null
    const cupedExplicitlySet = getCupedSelection(experiment.stats_config?.cuped) !== 'default'
    const cupedEnabled = resolveCupedEnabled(experiment.stats_config?.cuped, teamDefaultCupedEnabled)
    const cupedLookbackDays = resolveCupedLookbackDays(
        experiment.stats_config?.cuped,
        teamDefaultCupedLookbackDays,
        DEFAULT_LOOKBACK_DAYS
    )

    const teamDefaultSequentialEnabled = experimentsConfig?.default_sequential_testing_enabled ?? false
    const sequentialEnabled = resolveSequentialEnabled(
        experiment.stats_config?.frequentist,
        teamDefaultSequentialEnabled
    )

    const returnTo = urls.experiment(experiment.id)

    // Only show alerts section for saved experiments, as the alert relies on experiment.id for filtering
    const shouldShowSignificanceAlerts = typeof experiment.id === 'number'

    return (
        <div className="flex flex-col gap-8">
            <div>
                <h2 className="font-semibold text-lg">Statistics</h2>
                <div className="flex items-center gap-2">
                    <span>
                        {isBayesian ? 'Bayesian' : 'Frequentist'} / {confidenceDisplay}
                        {!isBayesian && sequentialEnabled && ' · Sequential testing'}
                    </span>
                    <LemonButton type="secondary" size="xsmall" icon={<IconPencil />} onClick={openStatsEngineModal} />
                </div>
                <StatsMethodModal />
            </div>
            <div>
                <h2 className="font-semibold text-lg">CUPED</h2>
                <div className="flex items-center gap-2">
                    <LemonTag type={cupedEnabled ? 'success' : 'default'}>
                        {cupedEnabled ? 'Enabled' : 'Disabled'}
                    </LemonTag>
                    {cupedEnabled && <span>{cupedLookbackDays}-day lookback</span>}
                    <LemonButton type="secondary" size="xsmall" icon={<IconPencil />} onClick={openCupedModal} />
                </div>
                <p className="text-muted text-xs mt-1">
                    Use pre-experiment data to detect significant effects faster. Currently supported for mean and
                    funnel metrics.{' '}
                    {!cupedExplicitlySet && (
                        <>
                            Default is set in{' '}
                            <Link to={urls.settings('environment-experiments', 'environment-experiment-cuped-enabled')}>
                                environment settings
                            </Link>
                            .
                        </>
                    )}
                </p>
                <CupedModal />
            </div>
            <div>
                <h2 className="font-semibold text-lg">Baseline variant</h2>
                <LemonSelect
                    value={experiment.stats_config?.baseline_variant_key ?? 'control'}
                    options={variants.map((v) => ({
                        value: v.key,
                        label: v.key,
                    }))}
                    onChange={(value) => {
                        updateExperimentSettings({
                            stats_config: { ...experiment.stats_config, baseline_variant_key: value },
                        })
                    }}
                />
                <p className="text-muted text-xs mt-1">The variant all others are compared against.</p>
            </div>
            <div>
                <h2 className="font-semibold text-lg">Conversion windows</h2>
                <div className="flex items-center gap-2">
                    <LemonCheckbox
                        label="Require completed conversion or retention window"
                        checked={experiment.only_count_matured_users ?? false}
                        onChange={(checked) => {
                            updateExperimentSettings({ only_count_matured_users: checked })
                        }}
                    />
                </div>
                <p className="text-muted text-xs mt-1">
                    Exclude participants whose conversion or retention window hasn't elapsed yet. Default is set in{' '}
                    <Link to={urls.settings('environment-experiments', 'environment-experiment-matured-users')}>
                        environment settings
                    </Link>
                    .
                </p>
            </div>
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
