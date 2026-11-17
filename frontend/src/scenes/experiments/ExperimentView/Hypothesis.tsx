import { type ReactNode } from 'react'

import { IconInfo, IconPencil } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSelect, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SummarizeExperimentButton } from 'products/experiments/frontend/components/SummarizeExperimentButton'

import {
    BASELINE_HELP,
    COMPLETED_WINDOWS_HELP,
    CUPED_DEFAULT_SETTINGS_URL,
    CUPED_HELP,
    HYPOTHESIS_PLACEHOLDER,
    HypothesisModals,
    useHypothesisPanel,
} from './hypothesisPanel'
import { QuillHypothesis } from './QuillHypothesis'

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
    const panel = useHypothesisPanel()
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillHypothesis />
    }

    const { isBayesian, cupedEnabled, lockedReason, tags } = panel

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
                        onClick={panel.openDescriptionModal}
                    />
                </div>
                <div className="max-h-40 overflow-y-auto mt-1 pr-1" data-attr="experiment-hypothesis-text">
                    {panel.description ? (
                        <p className="metric-cell font-normal m-0 leading-relaxed whitespace-pre-wrap">
                            {panel.description}
                        </p>
                    ) : (
                        <p className="metric-cell font-normal m-0 leading-relaxed italic">{HYPOTHESIS_PLACEHOLDER}</p>
                    )}
                </div>
            </div>

            <div className="mt-auto flex flex-col gap-3">
                {panel.showResults && (
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
                            onEdit={panel.openStatsEngineModal}
                            editLabel="Edit statistics settings"
                            editDisabledReason={lockedReason}
                        >
                            <span>
                                {isBayesian ? 'Bayesian' : 'Frequentist'} · {panel.confidenceDisplay}
                                {!isBayesian && panel.sequentialEnabled && ' · Sequential testing'}
                            </span>
                        </SettingRow>
                        <SettingRow
                            label="CUPED"
                            info={CUPED_HELP}
                            onEdit={panel.openCupedModal}
                            editLabel="Edit CUPED settings"
                            editDisabledReason={lockedReason}
                        >
                            <LemonTag type={cupedEnabled ? 'success' : 'default'}>
                                {cupedEnabled ? 'Enabled' : 'Disabled'}
                            </LemonTag>
                            {cupedEnabled && <span>{panel.cupedLookbackDays}-day lookback</span>}
                            {panel.cupedFromTeamDefault && (
                                <Link className="text-xs" to={CUPED_DEFAULT_SETTINGS_URL}>
                                    Project default
                                </Link>
                            )}
                        </SettingRow>
                        <SettingRow label="Baseline variant" info={BASELINE_HELP}>
                            <LemonSelect
                                size="xsmall"
                                value={panel.baselineVariantKey}
                                loading={panel.saving}
                                disabledReason={lockedReason}
                                options={panel.variantKeys.map((key) => ({ value: key, label: key }))}
                                onChange={panel.setBaselineVariant}
                            />
                        </SettingRow>
                        <SettingRow label="Completed windows" info={COMPLETED_WINDOWS_HELP}>
                            <LemonCheckbox
                                label="Required"
                                labelClassName="font-normal"
                                checked={panel.onlyCountMaturedUsers}
                                disabledReason={lockedReason ?? (panel.saving ? 'Saving' : undefined)}
                                onChange={panel.setOnlyCountMaturedUsers}
                            />
                        </SettingRow>
                        <SettingRow label="Tags">
                            {panel.canEditExperiment ? (
                                <ObjectTags
                                    tags={tags}
                                    onChange={panel.setTags}
                                    saving={panel.saving}
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

            <HypothesisModals />
        </div>
    )
}
