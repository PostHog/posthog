import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonCollapse, LemonInput, LemonModal, LemonTable, Link } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { FeatureFlagFiltersSection } from 'scenes/feature-flags/FeatureFlagFilters'
import { slugifyFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'
import { urls } from 'scenes/urls'

import { Experiment, FeatureFlagType } from '~/types'

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
                <div className="text-muted">
                    Create a new experiment using the configuration from <strong>{experiment.name}</strong>.
                </div>

                <div>
                    <label className="font-semibold mb-1 block">Experiment name</label>
                    <LemonInput
                        value={experimentName}
                        onChange={handleNameChange}
                        placeholder="e.g., Checkout flow v2"
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
                                placeholder="e.g., checkout-flow-v2"
                                data-attr="template-flag-key"
                            />
                        </div>
                        <LemonButton
                            type="primary"
                            onClick={() => handleCreate()}
                            disabledReason={!canCreate ? 'Enter an experiment name' : undefined}
                            data-attr="template-create-button"
                        >
                            Create
                        </LemonButton>
                    </div>
                    <div className="text-xs text-muted mt-1">A new flag will be created with this key</div>
                </div>

                <LemonCollapse
                    panels={[
                        {
                            key: 'reuse',
                            header: 'Reuse a flag',
                            content: (
                                <div className="space-y-4">
                                    <div>
                                        <div className="font-semibold mb-2">Original experiment flag</div>
                                        <div className="flex items-center justify-between p-3 border rounded bg-bg-light">
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
                                                disabledReason={!canCreate ? 'Enter an experiment name' : undefined}
                                            >
                                                Select
                                            </LemonButton>
                                        </div>
                                    </div>

                                    <div>
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
