import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { commonActionFilterProps } from 'scenes/experiments/Metrics/Selectors'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'

import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { Query } from '~/queries/Query/Query'
import { NodeKind, TrendsQuery } from '~/queries/schema'
import { FilterType, PropertyMathType } from '~/types'

import { featureManagementEditLogic, FeatureMetric } from './featureManagementEditLogic'

export function FeatureManagementMetricsForm(): JSX.Element {
    const { featureForm } = useValues(featureManagementEditLogic)

    const { success_metrics, failure_metrics, exposure_metrics } = featureForm

    return (
        <div className="flex flex-col space-y-4">
            <div>
                <LemonLabel>Success metrics (optional)</LemonLabel>
                {success_metrics.map((metric, idx) => (
                    <FeatureManagementMetric
                        key={idx}
                        metric={metric}
                        onChange={() => alert(`Success metric ${idx} changed`)}
                    />
                ))}
                <LemonButton
                    type="secondary"
                    onClick={() => alert('Add metric')}
                    icon={<IconPlusSmall />}
                    data-attr="add-test-variant"
                >
                    Add metric
                </LemonButton>
            </div>
            <div>
                <LemonLabel>Failure metrics (optional)</LemonLabel>
                {failure_metrics.map((metric, idx) => (
                    <FeatureManagementMetric
                        key={idx}
                        metric={metric}
                        onChange={() => alert(`Failure metric ${idx} changed`)}
                    />
                ))}
                <LemonButton
                    type="secondary"
                    onClick={() => alert('Add metric')}
                    icon={<IconPlusSmall />}
                    data-attr="add-test-variant"
                >
                    Add metric
                </LemonButton>
            </div>
            <div>
                <LemonLabel>Exposure metrics (optional)</LemonLabel>
                {exposure_metrics.map((metric, idx) => (
                    <FeatureManagementMetric
                        key={idx}
                        metric={metric}
                        onChange={() => alert(`Exposure metric ${idx} changed`)}
                    />
                ))}
                <LemonButton
                    type="secondary"
                    onClick={() => alert('Add metric')}
                    icon={<IconPlusSmall />}
                    data-attr="add-test-variant"
                >
                    Add metric
                </LemonButton>
            </div>
        </div>
    )
}

function FeatureManagementMetricModal({
    metric,
    onChange,
    onDelete,
    isOpen,
    onClose,
}: {
    metric: FeatureMetric
    onChange: (updatedMetric: FeatureMetric) => void
    onDelete: () => void
    isOpen: boolean
    onClose: () => void
}): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1000}
            title="Edit feature metric"
            footer={
                <div className="flex items-center w-full">
                    <LemonButton
                        type="secondary"
                        status="danger"
                        onClick={() => {
                            LemonDialog.open({
                                title: 'Delete this metric?',
                                content: <div className="text-sm text-muted">This action cannot be undone.</div>,
                                primaryButton: {
                                    children: 'Delete',
                                    type: 'primary',
                                    onClick: onDelete,
                                    size: 'small',
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                    type: 'tertiary',
                                    size: 'small',
                                },
                            })
                        }}
                    >
                        Delete
                    </LemonButton>
                    <div className="flex items-center gap-2 ml-auto">
                        <LemonButton
                            form="edit-experiment-goal-form"
                            type="secondary"
                            onClick={onClose}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            form="edit-experiment-goal-form"
                            onClick}
                            type="primary"
                            loading={experimentLoading}
                            data-attr="create-annotation-submit"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="flex flex-col space-y-4">
                <LemonLabel>Name (optional)</LemonLabel>
                <LemonInput
                    value={metric.name}
                    onChange={(newName) => {
                        onChange({
                            ...metric,
                            name: newName,
                        })
                    }}
                />
                <ActionFilter
                    bordered
                    filters={queryNodeToFilter(metric.query)}
                    setFilters={(filters: Partial<FilterType>): void => {
                        const trendsQuery = filtersToQueryNode(filters)
                        onChange({
                            ...metric,
                            query: trendsQuery as TrendsQuery,
                        })
                    }}
                    typeKey="feature-management-metric"
                    buttonCopy="Add graph series"
                    showSeriesIndicator={true}
                    entitiesLimit={1}
                    showNumericalPropsOnly={true}
                    onlyPropertyMathDefinitions={[PropertyMathType.Average]}
                    {...commonActionFilterProps}
                />
                <div className="mt-4">
                    <Query
                        query={{
                            kind: NodeKind.InsightVizNode,
                            source: metric,
                            showTable: false,
                            showLastComputation: true,
                            showLastComputationRefresh: false,
                        }}
                        readOnly
                    />
                </div>
            </div>
        </LemonModal>
    )
}
