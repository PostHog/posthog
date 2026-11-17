import { useActions, useValues } from 'kea'
import { type ReactNode, useEffect, useState } from 'react'

import { IconInfo, IconPencil } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonModal, LemonSelect, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { experimentsConfigLogic } from 'scenes/settings/environment/experimentsConfigLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, ExperimentStatsMethod } from '~/types'

import { SummarizeExperimentButton } from 'products/experiments/frontend/components/SummarizeExperimentButton'
import { DEFAULT_LOOKBACK_DAYS } from 'products/experiments/frontend/constants'
import { hasEnded, isLaunched } from 'products/experiments/frontend/experimentStatus'
import { CupedModal } from 'products/experiments/frontend/modals/CupedModal/CupedModal'
import { StatsMethodModal } from 'products/experiments/frontend/modals/StatsMethodModal/StatsMethodModal'

import { experimentLogic, getSectionMetricUuids } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { getBaselineVariantKey } from '../utils'
import { getCupedSelection, resolveCupedEnabled, resolveCupedLookbackDays } from './cuped'
import { resolveSequentialEnabled } from './sequential'

function SettingRow({
    label,
    info,
    children,
    onEdit,
    editLabel,
    editDisabledReason,
}: {
    label: string
    info?: string
    children: ReactNode
    onEdit?: () => void
    editLabel?: string
    editDisabledReason?: string
}): JSX.Element {
    return (
        <>
            <dt className="text-secondary flex items-center gap-1 min-h-6">
                {label}
                {info && (
                    <Tooltip title={info}>
                        <IconInfo className="text-secondary text-base" />
                    </Tooltip>
                )}
            </dt>
            <dd className="m-0 flex items-center gap-1 min-h-6 min-w-0">
                {children}
                {onEdit && (
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        icon={<IconPencil className="text-secondary" />}
                        tooltip={editLabel}
                        aria-label={editLabel}
                        disabledReason={editDisabledReason}
                        onClick={onEdit}
                    />
                )}
            </dd>
        </>
    )
}

export function Hypothesis(): JSX.Element {
    const { experiment, statsMethod, variants, experimentUpdateLoading } = useValues(experimentLogic)
    const { updateExperiment, updateExperimentSettings } = useActions(experimentLogic)
    const { openDescriptionModal, closeDescriptionModal, openStatsEngineModal, openCupedModal } =
        useActions(modalsLogic)
    const { isDescriptionModalOpen } = useValues(modalsLogic)
    const { experimentsConfig } = useValues(experimentsConfigLogic)

    const [tempDescription, setTempDescription] = useState(experiment.description || '')

    useEffect(() => {
        setTempDescription(experiment.description || '')
    }, [experiment.description])

    const canEditExperiment = userHasAccess(
        AccessControlResourceType.Experiment,
        AccessControlLevel.Editor,
        experiment.user_access_level
    )

    const isBayesian = statsMethod === ExperimentStatsMethod.Bayesian
    const confidenceDisplay = isBayesian
        ? `${((experiment.stats_config?.bayesian?.ci_level ?? 0.95) * 100).toFixed(0)}%`
        : `${((1 - (experiment.stats_config?.frequentist?.alpha ?? 0.05)) * 100).toFixed(0)}%`
    const sequentialEnabled = resolveSequentialEnabled(
        experiment.stats_config?.frequentist,
        experimentsConfig?.default_sequential_testing_enabled ?? false
    )
    const cupedEnabled = resolveCupedEnabled(
        experiment.stats_config?.cuped,
        experimentsConfig?.default_cuped_enabled ?? false
    )
    const cupedLookbackDays = resolveCupedLookbackDays(
        experiment.stats_config?.cuped,
        experimentsConfig?.default_cuped_lookback_days ?? null,
        DEFAULT_LOOKBACK_DAYS
    )
    const cupedFromTeamDefault = getCupedSelection(experiment.stats_config?.cuped) === 'default'

    const tags = experiment.tags ?? []
    const showResults = isLaunched(experiment) && getSectionMetricUuids(experiment, false).length > 0
    const lockedReason = hasEnded(experiment) ? 'Settings are locked because this experiment has ended.' : undefined

    return (
        <div className="h-full border border-primary rounded bg-[var(--color-bg-table)] px-3 py-2.5 flex flex-col gap-3">
            <div className="min-h-0">
                <div className="flex items-center gap-1">
                    <span className="metric-cell-header font-bold">Hypothesis</span>
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        icon={<IconPencil className="text-secondary" />}
                        tooltip="Edit hypothesis"
                        onClick={openDescriptionModal}
                    />
                </div>
                <div className="max-h-40 overflow-y-auto mt-1 pr-1" data-attr="experiment-hypothesis-text">
                    {experiment.description ? (
                        <p className="metric-cell font-normal m-0 leading-relaxed whitespace-pre-wrap">
                            {experiment.description}
                        </p>
                    ) : (
                        <p className="metric-cell font-normal m-0 leading-relaxed italic">
                            Add your hypothesis for this test
                        </p>
                    )}
                </div>
            </div>

            <div className="mt-auto flex flex-col gap-3">
                {showResults && (
                    <div className="border-t border-primary pt-3">
                        <span className="metric-cell-header font-bold">Results</span>
                        <div className="mt-2">
                            <SummarizeExperimentButton />
                        </div>
                    </div>
                )}
                <div className="border-t border-primary pt-3">
                    <span className="metric-cell-header font-bold">Settings</span>
                    <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 m-0 mt-2 text-[13px]">
                        <SettingRow
                            label="Statistics"
                            onEdit={openStatsEngineModal}
                            editLabel="Edit statistics settings"
                            editDisabledReason={lockedReason}
                        >
                            <span>
                                {isBayesian ? 'Bayesian' : 'Frequentist'} · {confidenceDisplay}
                                {!isBayesian && sequentialEnabled && ' · Sequential testing'}
                            </span>
                        </SettingRow>
                        <SettingRow
                            label="CUPED"
                            info="Uses pre-experiment data to detect significant effects faster. Supported for mean and funnel metrics."
                            onEdit={openCupedModal}
                            editLabel="Edit CUPED settings"
                            editDisabledReason={lockedReason}
                        >
                            <LemonTag type={cupedEnabled ? 'success' : 'default'}>
                                {cupedEnabled ? 'Enabled' : 'Disabled'}
                            </LemonTag>
                            {cupedEnabled && <span>{cupedLookbackDays}-day lookback</span>}
                            {cupedFromTeamDefault && (
                                <Link
                                    className="text-xs"
                                    to={urls.settings(
                                        'environment-experiments',
                                        'environment-experiment-cuped-enabled'
                                    )}
                                >
                                    Project default
                                </Link>
                            )}
                        </SettingRow>
                        <SettingRow label="Baseline variant" info="The variant all others are compared against.">
                            <LemonSelect
                                size="xsmall"
                                value={getBaselineVariantKey(experiment)}
                                loading={experimentUpdateLoading}
                                disabledReason={lockedReason}
                                options={variants.map((v) => ({ value: v.key, label: v.key }))}
                                onChange={(value) => {
                                    updateExperimentSettings({
                                        stats_config: { ...experiment.stats_config, baseline_variant_key: value },
                                    })
                                }}
                            />
                        </SettingRow>
                        <SettingRow
                            label="Completed windows"
                            info="Exclude participants whose conversion or retention window hasn't elapsed yet. The project default is set in environment settings."
                        >
                            <LemonCheckbox
                                label="Required"
                                labelClassName="font-normal"
                                checked={experiment.only_count_matured_users ?? false}
                                disabledReason={lockedReason ?? (experimentUpdateLoading ? 'Saving' : undefined)}
                                onChange={(checked) => {
                                    updateExperimentSettings({ only_count_matured_users: checked })
                                }}
                            />
                        </SettingRow>
                        <SettingRow label="Tags">
                            {canEditExperiment ? (
                                <ObjectTags
                                    tags={tags}
                                    onChange={(newTags) => updateExperiment({ tags: newTags })}
                                    saving={experimentUpdateLoading}
                                    data-attr="experiment-tags"
                                />
                            ) : tags.length > 0 ? (
                                <ObjectTags tags={tags} staticOnly data-attr="experiment-tags" />
                            ) : (
                                <span className="text-secondary">None</span>
                            )}
                        </SettingRow>
                    </dl>
                </div>
            </div>

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
                    placeholder="Add your hypothesis for this test"
                    minRows={6}
                    maxLength={3000}
                />
            </LemonModal>
        </div>
    )
}
