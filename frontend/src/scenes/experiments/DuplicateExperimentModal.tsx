import { useActions, useValues } from 'kea'

import { LemonModal, LemonTable, Link } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { FeatureFlagFiltersSection } from 'scenes/feature-flags/FeatureFlagFilters'
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

    const handleDuplicate = (featureFlagKey?: string): void => {
        duplicateExperiment({ id: experiment.id as number, featureFlagKey })
        onClose()
    }

    const handleClose = (): void => {
        resetFeatureFlagModalFilters()
        onClose()
    }

    return (
        <LemonModal isOpen={isOpen} onClose={handleClose} title="Duplicate experiment" width="max-content">
            <div className="space-y-4">
                <div className="text-muted max-w-xl">
                    Select a feature flag for the duplicated experiment. You can reuse the original flag or choose a
                    different one. If the flag doesn't exist, create it first, then return to this page.
                </div>

                <div>
                    <div className="font-semibold mb-2">Use the same flag</div>
                    <div className="flex items-center justify-between p-3 border rounded bg-bg-light">
                        <div className="flex items-center" style={{ fontSize: '13px' }}>
                            <div className="font-semibold text-secondary">{experiment.feature_flag?.key}</div>
                            <Link
                                to={urls.featureFlag(experiment.feature_flag?.id as number)}
                                target="_blank"
                                className="flex items-center text-secondary"
                            >
                                <IconOpenInNew className="ml-1" />
                            </Link>
                        </div>
                        <LemonButton type="primary" size="xsmall" onClick={() => handleDuplicate()}>
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
                                        <div className="font-semibold">{key}</div>
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
                                    // Skip the current experiment's flag since we show it separately
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
        </LemonModal>
    )
}
