import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonCollapse, LemonInput, LemonModal, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

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

    const [experimentName, setExperimentName] = useState('')
    const [flagKey, setFlagKey] = useState('')
    const [flagKeyManuallyEdited, setFlagKeyManuallyEdited] = useState(false)

    const handleNameChange = (value: string): void => {
        setExperimentName(value)
        if (!flagKeyManuallyEdited) {
            setFlagKey(slugifyFeatureFlagKey(value, { fromTitleInput: true }))
        }
    }

    const handleFlagKeyChange = (value: string): void => {
        setFlagKeyManuallyEdited(true)
        setFlagKey(slugifyFeatureFlagKey(value))
    }

    const handleCreate = (overrideFlagKey?: string): void => {
        const finalFlagKey = overrideFlagKey ?? flagKey
        duplicateExperiment({
            id: experiment.id as number,
            featureFlagKey: finalFlagKey || undefined,
            name: experimentName || undefined,
        })
        onClose()
    }

    const handleClose = (): void => {
        resetFeatureFlagModalFilters()
        setExperimentName('')
        setFlagKey('')
        setFlagKeyManuallyEdited(false)
        onClose()
    }

    const canCreate = experimentName.trim().length > 0

    return (
        <LemonModal isOpen={isOpen} onClose={handleClose} title="New experiment from template" width="max-content">
            <div className="space-y-4 max-w-xl">
                <TemplateSummary experiment={experiment} />

                <div>
                    <div className="font-semibold mb-2">Experiment name</div>
                    <LemonInput
                        value={experimentName}
                        onChange={handleNameChange}
                        placeholder="e.g., Checkout flow v2"
                        autoFocus
                        data-attr="template-experiment-name"
                    />
                </div>

                <div>
                    <div className="font-semibold mb-2">Feature flag</div>
                    <div className="space-y-3">
                        <div className="flex items-center justify-between p-3 border rounded bg-bg-light gap-3">
                            <div className="flex-1 min-w-0">
                                <LemonInput
                                    value={flagKey}
                                    onChange={handleFlagKeyChange}
                                    placeholder="e.g., checkout-flow-v2"
                                    size="small"
                                    data-attr="template-flag-key"
                                />
                                <div className="text-xs text-muted mt-1">A new flag will be created with this key</div>
                            </div>
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={() => handleCreate()}
                                disabledReason={!canCreate ? 'Enter an experiment name' : undefined}
                                data-attr="template-create-button"
                            >
                                Create
                            </LemonButton>
                        </div>
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
                                                onClick={() => handleCreate(experiment.feature_flag?.key)}
                                                disabledReason={!canCreate ? 'Enter an experiment name' : undefined}
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
                                                        if (!disabledReason && !canCreate) {
                                                            disabledReason = 'Enter an experiment name'
                                                        }
                                                        return (
                                                            <LemonButton
                                                                size="xsmall"
                                                                type="primary"
                                                                disabledReason={disabledReason}
                                                                onClick={() => handleCreate(flag.key)}
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
