import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonCollapse, LemonModal, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import {
    experimentsLogic,
    getExperimentStatus,
    getExperimentStatusColor,
    getExperimentStatusLabel,
    isExperimentPaused,
} from 'scenes/experiments/experimentsLogic'
import { FeatureFlagFiltersSection } from 'scenes/feature-flags/FeatureFlagFilters'
import { slugifyFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'
import { urls } from 'scenes/urls'

import { Experiment, ExperimentConclusion, ExperimentStatus, FeatureFlagType } from '~/types'

import { CONCLUSION_DISPLAY_CONFIG } from './constants'
import { featureFlagEligibleForExperiment } from './utils'

interface DuplicateExperimentModalProps {
    isOpen: boolean
    onClose: () => void
    experiment: Experiment
}

function generateFlagKey(experimentName: string): string {
    const base = slugifyFeatureFlagKey(experimentName, { fromTitleInput: true })
    return base ? `${base}-copy` : 'experiment-copy'
}

function TemplateSummary({ experiment }: { experiment: Experiment }): JSX.Element {
    const status = getExperimentStatus(experiment)
    const isPaused = isExperimentPaused(experiment)
    const primaryMetricCount = experiment.metrics?.length ?? 0
    const secondaryMetricCount = experiment.metrics_secondary?.length ?? 0
    const variants = experiment.parameters?.feature_flag_variants ?? []
    const isDraft = status === ExperimentStatus.Draft
    const hasNoMetrics = primaryMetricCount === 0 && secondaryMetricCount === 0

    return (
        <div className="space-y-3">
            <div className="border rounded p-3 bg-bg-light space-y-2">
                <div className="flex items-center gap-2">
                    <span className="font-semibold">{experiment.name}</span>
                    <LemonTag type={getExperimentStatusColor(status, isPaused)} size="small">
                        {getExperimentStatusLabel(status, isPaused)}
                    </LemonTag>
                    {experiment.conclusion && CONCLUSION_DISPLAY_CONFIG[experiment.conclusion] && (
                        <LemonTag
                            type={
                                experiment.conclusion === ExperimentConclusion.Won
                                    ? 'success'
                                    : experiment.conclusion === ExperimentConclusion.Lost
                                      ? 'danger'
                                      : 'muted'
                            }
                            size="small"
                        >
                            {CONCLUSION_DISPLAY_CONFIG[experiment.conclusion].title}
                        </LemonTag>
                    )}
                </div>
                {experiment.description && <div className="text-muted text-sm">{experiment.description}</div>}
                <div className="flex items-center gap-4 text-sm text-muted">
                    <span>
                        {primaryMetricCount} primary {primaryMetricCount === 1 ? 'metric' : 'metrics'}
                        {secondaryMetricCount > 0 && `, ${secondaryMetricCount} secondary`}
                    </span>
                    {variants.length > 0 && (
                        <span>
                            {variants.length} {variants.length === 1 ? 'variant' : 'variants'} (
                            {variants.map((v) => v.key).join(', ')})
                        </span>
                    )}
                    {experiment.feature_flag?.key && (
                        <span className="flex items-center gap-0.5">
                            Flag: <code className="text-xs">{experiment.feature_flag.key}</code>
                        </span>
                    )}
                </div>
            </div>
            {isDraft && hasNoMetrics && (
                <LemonBanner type="warning">
                    This experiment is still in draft with no metrics configured. The new experiment will also be
                    incomplete.
                </LemonBanner>
            )}
            {isDraft && !hasNoMetrics && (
                <LemonBanner type="info">
                    This experiment is still in draft. Its configuration may be incomplete.
                </LemonBanner>
            )}
            {!isDraft && hasNoMetrics && (
                <LemonBanner type="warning">This experiment has no metrics configured.</LemonBanner>
            )}
        </div>
    )
}

export function DuplicateExperimentModal({ isOpen, onClose, experiment }: DuplicateExperimentModalProps): JSX.Element {
    const {
        featureFlagModalFeatureFlags,
        featureFlagModalFeatureFlagsLoading,
        featureFlagModalFilters,
        featureFlagModalPagination,
    } = useValues(experimentsLogic)
    const { duplicateExperiment, setFeatureFlagModalFilters, resetFeatureFlagModalFilters } =
        useActions(experimentsLogic)

    const [generatedFlagKey] = useState(() => generateFlagKey(experiment.name))

    const handleDuplicate = (featureFlagKey?: string): void => {
        duplicateExperiment({ id: experiment.id as number, featureFlagKey })
        onClose()
    }

    const handleClose = (): void => {
        resetFeatureFlagModalFilters()
        onClose()
    }

    return (
        <LemonModal isOpen={isOpen} onClose={handleClose} title="New experiment from template" width="max-content">
            <div className="space-y-4 max-w-xl">
                <TemplateSummary experiment={experiment} />

                <div>
                    <div className="font-semibold mb-2">Create a new flag</div>
                    <div className="flex items-center justify-between p-3 border rounded bg-bg-light">
                        <div className="text-sm">
                            A new flag <code className="text-xs">{generatedFlagKey}</code> will be created
                        </div>
                        <LemonButton type="primary" size="xsmall" onClick={() => handleDuplicate(generatedFlagKey)}>
                            Create
                        </LemonButton>
                    </div>
                </div>

                <LemonCollapse
                    panels={[
                        {
                            key: 'advanced',
                            header: 'Use a different flag',
                            content: (
                                <div className="space-y-4">
                                    <div>
                                        <div className="font-semibold mb-2">Reuse original flag</div>
                                        <div className="flex items-center justify-between p-3 border rounded bg-bg-light">
                                            <div className="flex items-center text-sm">
                                                <code className="text-xs">{experiment.feature_flag?.key}</code>
                                                <Link
                                                    to={urls.featureFlag(experiment.feature_flag?.id as number)}
                                                    target="_blank"
                                                    className="flex items-center text-secondary"
                                                >
                                                    <IconOpenInNew className="ml-1" />
                                                </Link>
                                            </div>
                                            <LemonButton
                                                type="secondary"
                                                size="xsmall"
                                                onClick={() => handleDuplicate()}
                                            >
                                                Select
                                            </LemonButton>
                                        </div>
                                    </div>

                                    <div>
                                        <div className="font-semibold mb-2">Choose an existing flag</div>
                                        <div className="mb-4">
                                            <FeatureFlagFiltersSection
                                                filters={featureFlagModalFilters}
                                                setFeatureFlagsFilters={setFeatureFlagModalFilters}
                                                searchPlaceholder="Search for feature flags"
                                                filtersConfig={{ search: true, type: true }}
                                            />
                                        </div>
                                        <LemonTable
                                            id="ff"
                                            dataSource={featureFlagModalFeatureFlags.results}
                                            loading={featureFlagModalFeatureFlagsLoading}
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
                                                        if (flag.key === experiment.feature_flag?.key) {
                                                            return null
                                                        }

                                                        let disabledReason: string | undefined = undefined
                                                        try {
                                                            featureFlagEligibleForExperiment(flag)
                                                        } catch (error) {
                                                            disabledReason = (error as Error).message
                                                        }
                                                        return (
                                                            <LemonButton
                                                                size="xsmall"
                                                                type="primary"
                                                                disabledReason={disabledReason}
                                                                onClick={() => handleDuplicate(flag.key)}
                                                            >
                                                                Select
                                                            </LemonButton>
                                                        )
                                                    },
                                                },
                                            ]}
                                            emptyState="No feature flags match these filters."
                                            pagination={featureFlagModalPagination}
                                            onSort={(newSorting) =>
                                                setFeatureFlagModalFilters({
                                                    order: newSorting
                                                        ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                                        : undefined,
                                                    page: 1,
                                                })
                                            }
                                        />
                                    </div>
                                </div>
                            ),
                        },
                    ]}
                />
            </div>
        </LemonModal>
    )
}
