import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSelect, LemonTag, Link } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { experimentsConfigLogic } from 'scenes/settings/environment/experimentsConfigLogic'
import { urls } from 'scenes/urls'

import { tagsModel } from '~/models/tagsModel'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ExperimentStatsMethod,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { DEFAULT_LOOKBACK_DAYS } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { getBaselineVariantKey } from '../utils'
import { getCupedSelection, resolveCupedEnabled, resolveCupedLookbackDays } from './cuped'
import { CupedModal } from './CupedModal'
import { resolveSequentialEnabled } from './sequential'
import { StatsMethodModal } from './StatsMethodModal'

export function SettingsTab(): JSX.Element {
    const { experiment, statsMethod, variants, experimentUpdateLoading } = useValues(experimentLogic)
    const { updateExperiment, updateExperimentSettings } = useActions(experimentLogic)
    const { openStatsEngineModal, openCupedModal } = useActions(modalsLogic)
    const { experimentsConfig } = useValues(experimentsConfigLogic)
    const { tags: allExistingTags } = useValues(tagsModel)

    const canEditExperiment = userHasAccess(
        AccessControlResourceType.Experiment,
        AccessControlLevel.Editor,
        experiment.user_access_level
    )

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
        <div className="flex flex-col gap-4">
            <div className="flex gap-4 flex-wrap items-start">
                <div className="flex-1 min-w-64 flex flex-col gap-4">
                    <div className="rounded border p-4 bg-bg-light flex flex-col gap-4">
                        <h2 className="font-semibold text-base m-0">Advanced options</h2>
                        <div className="flex flex-col gap-2">
                            <h3 className="text-sm font-medium m-0">Tags</h3>
                            {canEditExperiment ? (
                                <ObjectTags
                                    tags={experiment.tags ?? []}
                                    // Not updateExperimentSettings: tags don't affect metric
                                    // computation, so don't trigger its results refresh.
                                    onChange={(tags) => updateExperiment({ tags })}
                                    saving={experimentUpdateLoading}
                                    tagsAvailable={allExistingTags.filter(
                                        (tag: string) => !experiment.tags?.includes(tag)
                                    )}
                                    actionButtonSize="medium"
                                    data-attr="experiment-tags"
                                />
                            ) : (
                                <ObjectTags tags={experiment.tags ?? []} staticOnly data-attr="experiment-tags" />
                            )}
                        </div>
                    </div>
                </div>

                <div className="flex-[2] min-w-80 flex flex-col gap-4">
                    <div className="rounded border p-4 bg-bg-light flex flex-col gap-4">
                        <h2 className="font-semibold text-base m-0">Statistics</h2>
                        <div className="flex flex-col gap-2">
                            <h3 className="text-sm font-medium m-0">Method</h3>
                            <div className="flex items-center gap-2">
                                <span>
                                    {isBayesian ? 'Bayesian' : 'Frequentist'} / {confidenceDisplay}
                                    {!isBayesian && sequentialEnabled && ' · Sequential testing'}
                                </span>
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    icon={<IconPencil />}
                                    onClick={openStatsEngineModal}
                                />
                            </div>
                            <StatsMethodModal />
                        </div>
                        <div className="flex flex-col gap-2">
                            <h3 className="text-sm font-medium m-0">CUPED</h3>
                            <div className="flex items-center gap-2">
                                <LemonTag type={cupedEnabled ? 'success' : 'default'}>
                                    {cupedEnabled ? 'Enabled' : 'Disabled'}
                                </LemonTag>
                                {cupedEnabled && <span>{cupedLookbackDays}-day lookback</span>}
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    icon={<IconPencil />}
                                    onClick={openCupedModal}
                                />
                            </div>
                            <p className="text-muted text-xs m-0">
                                Use pre-experiment data to detect significant effects faster. Currently supported for
                                mean and funnel metrics.{' '}
                                {!cupedExplicitlySet && (
                                    <>
                                        Default is set in{' '}
                                        <Link
                                            to={urls.settings(
                                                'environment-experiments',
                                                'environment-experiment-cuped-enabled'
                                            )}
                                        >
                                            environment settings
                                        </Link>
                                        .
                                    </>
                                )}
                            </p>
                            <CupedModal />
                        </div>
                        <div className="flex flex-col gap-2">
                            <h3 className="text-sm font-medium m-0">Baseline variant</h3>
                            <div>
                                <LemonSelect
                                    value={getBaselineVariantKey(experiment)}
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
                            </div>
                            <p className="text-muted text-xs m-0">The variant all others are compared against.</p>
                        </div>
                        <div className="flex flex-col gap-2">
                            <h3 className="text-sm font-medium m-0">Conversion windows</h3>
                            <div className="flex items-center gap-2">
                                <LemonCheckbox
                                    label="Require completed conversion or retention window"
                                    checked={experiment.only_count_matured_users ?? false}
                                    onChange={(checked) => {
                                        updateExperimentSettings({ only_count_matured_users: checked })
                                    }}
                                />
                            </div>
                            <p className="text-muted text-xs m-0">
                                Exclude participants whose conversion or retention window hasn't elapsed yet. Default is
                                set in{' '}
                                <Link
                                    to={urls.settings(
                                        'environment-experiments',
                                        'environment-experiment-matured-users'
                                    )}
                                >
                                    environment settings
                                </Link>
                                .
                            </p>
                        </div>
                    </div>

                    {shouldShowSignificanceAlerts && (
                        <div className="rounded border p-4 bg-bg-light flex flex-col gap-2">
                            <h2 className="font-semibold text-base m-0">Notifications</h2>
                            <p className="text-muted text-xs m-0">Get notified when a metric reaches significance.</p>
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
            </div>
        </div>
    )
}
