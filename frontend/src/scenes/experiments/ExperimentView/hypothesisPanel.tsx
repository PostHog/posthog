import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { experimentsConfigLogic } from 'scenes/settings/environment/experimentsConfigLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, ExperimentStatsMethod } from '~/types'

import { DEFAULT_LOOKBACK_DAYS } from 'products/experiments/frontend/constants'
import { hasEnded, isLaunched } from 'products/experiments/frontend/experimentStatus'
import { CupedModal } from 'products/experiments/frontend/modals/CupedModal/CupedModal'
import { StatsMethodModal } from 'products/experiments/frontend/modals/StatsMethodModal/StatsMethodModal'

import { experimentLogic, getSectionMetricUuids } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { getBaselineVariantKey, isLegacyExperiment } from '../utils'
import { getCupedSelection, resolveCupedEnabled, resolveCupedLookbackDays } from './cuped'
import { resolveSequentialEnabled } from './sequential'

export const HYPOTHESIS_PLACEHOLDER = 'Add your hypothesis for this test'
export const CUPED_HELP =
    'Uses pre-experiment data to detect significant effects faster. Supported for mean and funnel metrics.'
export const BASELINE_HELP = 'The variant all others are compared against.'
export const COMPLETED_WINDOWS_HELP =
    "Exclude participants whose conversion or retention window hasn't elapsed yet. The project default is set in environment settings."
export const CUPED_DEFAULT_SETTINGS_URL = urls.settings(
    'environment-experiments',
    'environment-experiment-cuped-enabled'
)

export interface HypothesisPanel {
    description: string | null | undefined
    isBayesian: boolean
    confidenceDisplay: string
    sequentialEnabled: boolean
    cupedEnabled: boolean
    cupedLookbackDays: number
    cupedFromTeamDefault: boolean
    tags: string[]
    canEditExperiment: boolean
    showResults: boolean
    lockedReason: string | undefined
    variantKeys: string[]
    baselineVariantKey: string
    onlyCountMaturedUsers: boolean
    saving: boolean
    openDescriptionModal: () => void
    openStatsEngineModal: () => void
    openCupedModal: () => void
    setBaselineVariant: (value: string) => void
    setOnlyCountMaturedUsers: (checked: boolean) => void
    setTags: (tags: string[]) => void
}

export function useHypothesisPanel(): HypothesisPanel {
    const { experiment, statsMethod, variants, experimentUpdateLoading } = useValues(experimentLogic)
    const { updateExperiment, updateExperimentSettings } = useActions(experimentLogic)
    const { openDescriptionModal, openStatsEngineModal, openCupedModal } = useActions(modalsLogic)
    const { experimentsConfig } = useValues(experimentsConfigLogic)

    const isBayesian = statsMethod === ExperimentStatsMethod.Bayesian
    const isLegacy = isLegacyExperiment(experiment)

    return {
        description: experiment.description,
        isBayesian,
        confidenceDisplay: isBayesian
            ? `${((experiment.stats_config?.bayesian?.ci_level ?? 0.95) * 100).toFixed(0)}%`
            : `${((1 - (experiment.stats_config?.frequentist?.alpha ?? 0.05)) * 100).toFixed(0)}%`,
        sequentialEnabled: resolveSequentialEnabled(
            experiment.stats_config?.frequentist,
            experimentsConfig?.default_sequential_testing_enabled ?? false
        ),
        cupedEnabled: resolveCupedEnabled(
            experiment.stats_config?.cuped,
            experimentsConfig?.default_cuped_enabled ?? false
        ),
        cupedLookbackDays: resolveCupedLookbackDays(
            experiment.stats_config?.cuped,
            experimentsConfig?.default_cuped_lookback_days ?? null,
            DEFAULT_LOOKBACK_DAYS
        ),
        cupedFromTeamDefault: getCupedSelection(experiment.stats_config?.cuped) === 'default',
        tags: experiment.tags ?? [],
        canEditExperiment: userHasAccess(
            AccessControlResourceType.Experiment,
            AccessControlLevel.Editor,
            experiment.user_access_level
        ),
        showResults: !isLegacy && isLaunched(experiment) && getSectionMetricUuids(experiment, false).length > 0,
        lockedReason: isLegacy
            ? "Legacy experiments don't calculate results, so analysis settings are locked. Migrate this experiment to change them."
            : hasEnded(experiment)
              ? 'Settings are locked because this experiment has ended.'
              : undefined,
        variantKeys: variants.map((variant) => variant.key),
        baselineVariantKey: getBaselineVariantKey(experiment),
        onlyCountMaturedUsers: experiment.only_count_matured_users ?? false,
        saving: experimentUpdateLoading,
        openDescriptionModal,
        openStatsEngineModal,
        openCupedModal,
        setBaselineVariant: (value: string): void =>
            updateExperimentSettings({
                stats_config: { ...experiment.stats_config, baseline_variant_key: value },
            }),
        setOnlyCountMaturedUsers: (checked: boolean): void =>
            updateExperimentSettings({ only_count_matured_users: checked }),
        setTags: (tags: string[]): void => updateExperiment({ tags }),
    }
}

export function HypothesisModals(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { updateExperiment } = useActions(experimentLogic)
    const { isDescriptionModalOpen } = useValues(modalsLogic)
    const { closeDescriptionModal } = useActions(modalsLogic)

    const [tempDescription, setTempDescription] = useState(experiment.description || '')

    useEffect(() => {
        setTempDescription(experiment.description || '')
    }, [experiment.description])

    return (
        <>
            <StatsMethodModal />
            <CupedModal />
            <LemonModal
                isOpen={isDescriptionModalOpen}
                onClose={closeDescriptionModal}
                title="Edit hypothesis"
                footer={
                    <div className="flex items-center gap-2 justify-end">
                        <LemonButton type="secondary" onClick={closeDescriptionModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                updateExperiment({ description: tempDescription })
                                closeDescriptionModal()
                            }}
                        >
                            Save
                        </LemonButton>
                    </div>
                }
            >
                <LemonTextArea
                    className="w-full"
                    value={tempDescription}
                    onChange={(value) => setTempDescription(value)}
                    placeholder={HYPOTHESIS_PLACEHOLDER}
                    minRows={6}
                    maxLength={3000}
                />
            </LemonModal>
        </>
    )
}
