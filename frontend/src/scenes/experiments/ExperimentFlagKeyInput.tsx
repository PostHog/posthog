import { IconCopy } from '@posthog/icons'
import { LemonBanner, LemonInput, LemonTable, Link } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { FeatureFlagFiltersSection } from 'scenes/feature-flags/FeatureFlagFilters'
import { FeatureFlagsFilters } from 'scenes/feature-flags/featureFlagsLogic'
import { urls } from 'scenes/urls'

import { Experiment, FeatureFlagType } from '~/types'

import { hasEnded, isLaunched } from 'products/experiments/frontend/experimentStatus'

import { featureFlagEligibleForExperiment } from './utils'

export interface ExperimentFlagKeyInputProps {
    flagKey: string
    onFlagKeyChange: (value: string) => void
    isExistingFlag: boolean
    sourceExperiment: Experiment
    featureFlags: { results: FeatureFlagType[]; count: number }
    featureFlagsLoading: boolean
    featureFlagFilters: Partial<FeatureFlagsFilters>
    onFeatureFlagFiltersChange: (filters: Partial<FeatureFlagsFilters>) => void
    featureFlagPagination: PaginationManual
    onSelectExistingFlag: (key: string) => void
    showReuseFlag: boolean
    onToggleReuseFlag: (show: boolean) => void
}

export const FLAG_KEY_PLACEHOLDER = 'Auto-generated from name'
export const RESET_ANALYSIS_DOCS_URL = 'https://posthog.com/docs/experiments/managing-lifecycle'
export const REUSE_FLAG_LABEL = 'Reuse an existing feature flag'
export const NO_MATCHING_FLAGS = 'No feature flags match these filters.'

export function flagKeyHint(flagKey: string, isExistingFlag: boolean, sourceExperiment: Experiment): string {
    return isExistingFlag
        ? flagKey === sourceExperiment.feature_flag?.key
            ? 'This experiment will reuse the same flag as the original'
            : 'This experiment will use an existing flag'
        : 'A new flag will be created with this key'
}

export function ReuseFlagCopy({ ongoing, resetLink }: { ongoing: boolean; resetLink: JSX.Element }): JSX.Element {
    return ongoing ? (
        <>
            This experiment has not ended yet. Reusing its flag in a new experiment will cause data contamination, since
            both will count the same exposures and events. To re-run this experiment, use {resetLink} instead.
        </>
    ) : (
        <>
            Each experiment should have its own flag to avoid data contamination. To re-run an experiment with the same
            flag, use {resetLink} instead.
        </>
    )
}

export function flagSelectDisabledReason(flag: FeatureFlagType): string | undefined {
    try {
        featureFlagEligibleForExperiment(flag)
    } catch (error) {
        return (error as Error).message
    }
    return undefined
}

export function isOngoingExperiment(experiment: Experiment): boolean {
    return isLaunched(experiment) && !hasEnded(experiment)
}

export function ExperimentFlagKeyInput({
    flagKey,
    onFlagKeyChange,
    isExistingFlag,
    sourceExperiment,
    featureFlags,
    featureFlagsLoading,
    featureFlagFilters,
    onFeatureFlagFiltersChange,
    featureFlagPagination,
    onSelectExistingFlag,
    showReuseFlag,
    onToggleReuseFlag,
}: ExperimentFlagKeyInputProps): JSX.Element {
    const resetAnalysisLink = (
        <Link to={RESET_ANALYSIS_DOCS_URL} target="_blank">
            Reset analysis
        </Link>
    )
    const isOngoing = isOngoingExperiment(sourceExperiment)

    return (
        <>
            <div>
                <label className="font-semibold mb-1 block">Feature flag key</label>
                <LemonInput
                    value={flagKey}
                    onChange={onFlagKeyChange}
                    placeholder={FLAG_KEY_PLACEHOLDER}
                    data-attr="experiment-flag-key-input"
                />
                {flagKey && (
                    <div className="text-xs text-muted mt-1">
                        {flagKeyHint(flagKey, isExistingFlag, sourceExperiment)}
                    </div>
                )}
                {isExistingFlag &&
                    (isOngoing ? (
                        <LemonBanner type="warning" className="mt-2">
                            <ReuseFlagCopy ongoing resetLink={resetAnalysisLink} />
                        </LemonBanner>
                    ) : (
                        <LemonBanner type="info" className="mt-2">
                            <ReuseFlagCopy ongoing={false} resetLink={resetAnalysisLink} />
                        </LemonBanner>
                    ))}
            </div>

            {!showReuseFlag ? (
                <div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconCopy />}
                        onClick={() => onToggleReuseFlag(true)}
                    >
                        {REUSE_FLAG_LABEL}
                    </LemonButton>
                </div>
            ) : (
                <div>
                    <div className="font-semibold mb-2">Use the same flag</div>
                    <div className="flex items-center justify-between p-3 border rounded bg-bg-light mb-3">
                        <div className="flex items-center gap-1 text-sm">
                            <code className="text-xs">{sourceExperiment.feature_flag?.key}</code>
                            <Link
                                to={urls.featureFlag(sourceExperiment.feature_flag?.id as number)}
                                target="_blank"
                                className="flex items-center text-secondary"
                            >
                                <IconOpenInNew className="ml-0.5" />
                            </Link>
                        </div>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            onClick={() => onSelectExistingFlag(sourceExperiment.feature_flag?.key ?? '')}
                        >
                            Select
                        </LemonButton>
                    </div>
                    <div className="font-semibold mb-2">Choose an existing flag</div>
                    <FeatureFlagFiltersSection
                        filters={featureFlagFilters as FeatureFlagsFilters}
                        setFeatureFlagsFilters={onFeatureFlagFiltersChange}
                        searchPlaceholder="Search for feature flags"
                        filtersConfig={{ search: true, type: true }}
                    />
                    <LemonTable
                        id="ff"
                        className="mt-2"
                        dataSource={featureFlags.results}
                        loading={featureFlagsLoading}
                        useURLForSorting={false}
                        columns={[
                            {
                                title: 'Key',
                                dataIndex: 'key',
                                sorter: (a, b) => (a.key || '').localeCompare(b.key || ''),
                                render: (key, flag) => (
                                    <div className="flex items-center">
                                        <div className="font-semibold">{String(key ?? '')}</div>
                                        <Link
                                            to={urls.featureFlag(flag.id as number)}
                                            target="_blank"
                                            className="flex items-center"
                                        >
                                            <IconOpenInNew className="ml-1" />
                                        </Link>
                                    </div>
                                ),
                            },
                            {
                                title: 'Name',
                                dataIndex: 'name',
                                sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
                            },
                            {
                                title: null,
                                render: function RenderActions(_, flag: FeatureFlagType) {
                                    if (flag.key === sourceExperiment.feature_flag?.key) {
                                        return null
                                    }

                                    const disabledReason = flagSelectDisabledReason(flag)
                                    return (
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            disabledReason={disabledReason}
                                            onClick={() => onSelectExistingFlag(flag.key ?? '')}
                                        >
                                            Select
                                        </LemonButton>
                                    )
                                },
                            },
                        ]}
                        emptyState={NO_MATCHING_FLAGS}
                        pagination={featureFlagPagination}
                        onSort={(newSorting) =>
                            onFeatureFlagFiltersChange({
                                order: newSorting
                                    ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                    : undefined,
                                page: 1,
                            })
                        }
                    />
                </div>
            )}
        </>
    )
}
