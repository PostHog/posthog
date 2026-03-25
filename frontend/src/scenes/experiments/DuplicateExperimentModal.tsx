import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonInput, LemonModal, LemonTable, Link } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { experimentsLogic, getExperimentStatus } from 'scenes/experiments/experimentsLogic'
import { FeatureFlagFiltersSection } from 'scenes/feature-flags/FeatureFlagFilters'
import { slugifyFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'
import { urls } from 'scenes/urls'

import { Experiment, ExperimentStatus, FeatureFlagType } from '~/types'

import { featureFlagEligibleForExperiment } from './utils'

interface DuplicateExperimentModalProps {
    isOpen: boolean
    onClose: () => void
    experiment: Experiment
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
            name: experimentName.trim() || undefined,
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

    return (
        <LemonModal isOpen={isOpen} onClose={handleClose} title="New experiment from template" width="max-content">
            <div className="space-y-4">
                <div className="text-muted max-w-xl">
                    Create a new experiment using the configuration from <strong>{experiment.name}</strong>.
                </div>

                <div>
                    <label className="font-semibold mb-1 block">Experiment name</label>
                    <LemonInput
                        value={experimentName}
                        onChange={handleNameChange}
                        placeholder={`${experiment.name} (Copy)`}
                        autoFocus
                        data-attr="template-experiment-name"
                    />
                </div>

                <div>
                    <label className="font-semibold mb-1 block">Feature flag key</label>
                    <div className="flex items-center gap-2">
                        <div className="flex-1">
                            <LemonInput
                                value={flagKey}
                                onChange={handleFlagKeyChange}
                                placeholder="Auto-generated from name"
                                data-attr="template-flag-key"
                            />
                        </div>
                        <LemonButton type="primary" onClick={() => handleCreate()} data-attr="template-create-button">
                            Create
                        </LemonButton>
                    </div>
                    <div className="text-xs text-muted mt-1">
                        {flagKey
                            ? 'A new flag will be created with this key'
                            : 'Leave empty to auto-generate a flag from the experiment name'}
                    </div>
                </div>

                <div>
                    <div className="font-semibold mb-2">Reuse a flag</div>
                    {(() => {
                        const resetAnalysisLink = (
                            <Link to="https://posthog.com/docs/experiments/managing-lifecycle" target="_blank">
                                Reset analysis
                            </Link>
                        )
                        return getExperimentStatus(experiment) === ExperimentStatus.Running ? (
                            <LemonBanner type="warning" className="mb-3">
                                This experiment is currently running. Reusing its flag in a new experiment without
                                ending this one first will cause data contamination because both experiments will count
                                the same exposures and goal events. To re-run this experiment with the same flag,
                                consider using {resetAnalysisLink} instead.
                            </LemonBanner>
                        ) : (
                            <LemonBanner type="info" className="mb-3">
                                Each experiment should have its own flag to avoid data contamination. To re-run an
                                experiment with the same flag, consider using {resetAnalysisLink} instead.
                            </LemonBanner>
                        )
                    })()}
                    <div className="flex items-center justify-between p-3 border rounded bg-bg-light mb-4">
                        <div className="flex items-center gap-1 text-sm">
                            <code className="text-xs">{experiment.feature_flag?.key}</code>
                            <Link
                                to={urls.featureFlag(experiment.feature_flag?.id as number)}
                                target="_blank"
                                className="flex items-center text-secondary"
                            >
                                <IconOpenInNew className="ml-0.5" />
                            </Link>
                        </div>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            onClick={() => handleCreate(experiment.feature_flag?.key)}
                        >
                            Select
                        </LemonButton>
                    </div>

                    <div className="font-semibold mb-2">Choose an existing flag</div>
                    <FeatureFlagFiltersSection
                        filters={featureFlagModalFilters}
                        setFeatureFlagsFilters={setFeatureFlagModalFilters}
                        searchPlaceholder="Search for feature flags"
                        filtersConfig={{ search: true, type: true }}
                    />
                    <LemonTable
                        id="ff"
                        className="mt-2"
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
        </LemonModal>
    )
}
