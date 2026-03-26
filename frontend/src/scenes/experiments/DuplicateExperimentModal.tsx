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
    const [isExistingFlag, setIsExistingFlag] = useState(false)
    const [showReuseFlag, setShowReuseFlag] = useState(false)

    const handleNameChange = (value: string): void => {
        setExperimentName(value)
        if (!flagKeyManuallyEdited) {
            setFlagKey(slugifyFeatureFlagKey(value, { fromTitleInput: true }))
            setIsExistingFlag(false)
        }
    }

    const handleFlagKeyChange = (value: string): void => {
        setFlagKeyManuallyEdited(true)
        setIsExistingFlag(false)
        setFlagKey(slugifyFeatureFlagKey(value))
    }

    const selectExistingFlag = (key: string): void => {
        setFlagKeyManuallyEdited(true)
        setIsExistingFlag(true)
        setFlagKey(key)
    }

    const handleDuplicate = (): void => {
        duplicateExperiment({
            id: experiment.id as number,
            featureFlagKey: flagKey || undefined,
            name: experimentName.trim() || undefined,
        })
        handleClose()
    }

    const handleClose = (): void => {
        resetFeatureFlagModalFilters()
        setExperimentName('')
        setFlagKey('')
        setFlagKeyManuallyEdited(false)
        setIsExistingFlag(false)
        setShowReuseFlag(false)
        onClose()
    }

    const resetAnalysisLink = (
        <Link to="https://posthog.com/docs/experiments/managing-lifecycle" target="_blank">
            Reset analysis
        </Link>
    )

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleClose}
            title="Duplicate experiment"
            width="max-content"
            footer={
                <div className="flex justify-end">
                    <LemonButton type="primary" onClick={handleDuplicate} data-attr="duplicate-experiment-submit">
                        Duplicate
                    </LemonButton>
                </div>
            }
        >
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
                        data-attr="duplicate-experiment-name"
                    />
                </div>

                <div>
                    <label className="font-semibold mb-1 block">Feature flag key</label>
                    <LemonInput
                        value={flagKey}
                        onChange={handleFlagKeyChange}
                        placeholder="Auto-generated from name"
                        data-attr="duplicate-experiment-flag-key"
                    />
                    {flagKey && (
                        <div className="text-xs text-muted mt-1">
                            {isExistingFlag
                                ? flagKey === experiment.feature_flag?.key
                                    ? 'This experiment will reuse the same flag as the original'
                                    : 'This experiment will use an existing flag'
                                : 'A new flag will be created with this key'}
                        </div>
                    )}
                    {isExistingFlag &&
                        (getExperimentStatus(experiment) === ExperimentStatus.Running ? (
                            <LemonBanner type="warning" className="mt-2">
                                This experiment is still running. Reusing its flag in a new experiment will cause data
                                contamination, since both will count the same exposures and events. To re-run this
                                experiment, use {resetAnalysisLink} instead.
                            </LemonBanner>
                        ) : (
                            <LemonBanner type="info" className="mt-2">
                                Each experiment should have its own flag to avoid data contamination. To re-run an
                                experiment with the same flag, use {resetAnalysisLink} instead.
                            </LemonBanner>
                        ))}
                </div>

                {!showReuseFlag ? (
                    <Link subtle onClick={() => setShowReuseFlag(true)} className="text-sm">
                        Want to reuse an existing feature flag?
                    </Link>
                ) : (
                    <div>
                        <div className="font-semibold mb-2">Use the same flag</div>
                        <div className="flex items-center justify-between p-3 border rounded bg-bg-light mb-3">
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
                                onClick={() => selectExistingFlag(experiment.feature_flag?.key ?? '')}
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
                                                type="secondary"
                                                disabledReason={disabledReason}
                                                onClick={() => selectExistingFlag(flag.key ?? '')}
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
                )}
            </div>
        </LemonModal>
    )
}
