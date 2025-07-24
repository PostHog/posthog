import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonModal, LemonTable, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { urls } from 'scenes/urls'

import { Experiment, FeatureFlagType } from '~/types'

import { featureFlagEligibleForExperiment } from './utils'

interface DuplicateExperimentModalProps {
    isOpen: boolean
    onClose: () => void
    experiment: Experiment
}

export function DuplicateExperimentModal({ isOpen, onClose, experiment }: DuplicateExperimentModalProps): JSX.Element {
    const { featureFlags } = useValues(experimentsLogic)
    const { duplicateExperiment } = useActions(experimentsLogic)

    const handleDuplicate = (featureFlagKey?: string): void => {
        duplicateExperiment({ id: experiment.id as number, featureFlagKey })
        onClose()
    }

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="Duplicate experiment" width="max-content">
            <div className="space-y-4">
                <div className="text-muted max-w-xl">
                    Select a feature flag for the duplicated experiment. You can use the same flag as the original
                    experiment or choose a different one.
                </div>

                <div className="flex items-center justify-between p-3 border rounded bg-bg-light">
                    <div>
                        <div className="font-semibold">Use the same flag</div>
                        <div className="text-sm text-muted">{experiment.feature_flag?.key}</div>
                    </div>
                    <LemonButton type="primary" onClick={() => handleDuplicate()}>
                        Select
                    </LemonButton>
                </div>

                <div className="text-center text-muted">
                    or choose a different flag. To use a new flag, create it first then select it here.
                </div>

                <LemonTable
                    dataSource={featureFlags.results}
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
                                        size="small"
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
                />
            </div>
        </LemonModal>
    )
}
