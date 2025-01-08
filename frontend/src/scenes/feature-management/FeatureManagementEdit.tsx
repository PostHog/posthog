import { IconExternal, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonLabel, LemonModal, LemonTextArea, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { InsightModel } from '~/types'

import { featureManagementEditLogic } from './featureManagementEditLogic'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { commonActionFilterProps } from 'scenes/experiments/Metrics/Selectors'

export const scene: SceneExport = {
    component: FeatureManagementEdit,
    logic: featureManagementEditLogic,
    paramsToProps: ({ params: { id } }): (typeof featureManagementEditLogic)['props'] => ({
        id: id && id !== 'new' ? id : 'new',
    }),
}

function FeatureManagementEdit(): JSX.Element {
    const { props, featureForm } = useValues(featureManagementEditLogic)

    return (
        <Form
            id="feature-creation"
            logic={featureManagementEditLogic}
            props={props}
            formKey="featureForm"
            enableFormOnSubmit
            className="space-y-4"
        >
            <PageHeader
                buttons={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            data-attr="cancel-feature-flag"
                            type="secondary"
                            onClick={() => router.actions.push(urls.featureManagement())}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="save-feature-flag"
                            htmlType="submit"
                            form="feature-creation"
                        >
                            Save
                        </LemonButton>
                    </div>
                }
            />
            <div className="my-4">
                <div className="max-w-1/2 space-y-4">
                    <LemonField name="name" label="Name">
                        <LemonInput
                            data-attr="feature-name"
                            className="ph-ignore-input"
                            autoFocus
                            placeholder="examples: Login v2, New registration flow, Mobile web"
                            autoComplete="off"
                            autoCapitalize="off"
                            autoCorrect="off"
                            spellCheck={false}
                        />
                    </LemonField>

                    <LemonField name="key" label="Key">
                        <LemonInput
                            data-attr="feature-key"
                            className="ph-ignore-input"
                            autoComplete="off"
                            autoCapitalize="off"
                            autoCorrect="off"
                            spellCheck={false}
                            disabled
                        />
                    </LemonField>
                    <span className="text-muted text-sm">
                        This will be used to monitor feature usage. Feature keys must be unique to other features and
                        feature flags.
                    </span>

                    <LemonField name="description" label="Description">
                        <LemonTextArea className="ph-ignore-input" data-attr="feature-description" />
                    </LemonField>
                </div>
            </div>
            <LemonDivider />

            <div className="flex flex-col space-y-4">
                <div className="flex flex-col items-start space-y-2">
                    <LemonLabel>Success metrics (optional)</LemonLabel>
                    {featureForm.success_metrics.map((insight) => (
                        <FeatureManagementMetric
                            key={insight.short_id}
                            insight={insight}
                            onDelete={() => alert(`Delete metric ${insight.short_id}`)}
                        />
                    ))}
                    <LemonButton
                        type="secondary"
                        onClick={() => alert('Add metric')}
                        icon={<IconPlusSmall />}
                        size="xsmall"
                        data-attr="add-test-variant"
                    >
                        Add metric
                    </LemonButton>
                </div>
                <div className="flex flex-col items-start space-y-2">
                    <LemonLabel>Failure metrics (optional)</LemonLabel>
                    {featureForm.failure_metrics.map((insight) => (
                        <FeatureManagementMetric
                            key={insight.short_id}
                            insight={insight}
                            onDelete={() => alert(`Delete metric ${insight.short_id}`)}
                        />
                    ))}
                    <LemonButton
                        type="secondary"
                        onClick={() => alert('Add metric')}
                        icon={<IconPlusSmall />}
                        size="xsmall"
                        data-attr="add-test-variant"
                    >
                        Add metric
                    </LemonButton>
                </div>
                <div className="flex flex-col items-start space-y-2">
                    <LemonLabel>Exposure metrics (optional)</LemonLabel>
                    {featureForm.exposure_metrics.map((insight) => (
                        <FeatureManagementMetric
                            key={insight.short_id}
                            insight={insight}
                            onDelete={() => alert(`Delete metric ${insight.short_id}`)}
                        />
                    ))}
                    <LemonButton
                        type="secondary"
                        onClick={() => alert('Add metric')}
                        icon={<IconPlusSmall />}
                        size="xsmall"
                        data-attr="add-test-variant"
                    >
                        Add metric
                    </LemonButton>
                </div>
            </div>

            <LemonDivider />

            <div className="flex items-center gap-2 justify-end">
                <LemonButton
                    data-attr="cancel-feature-flag"
                    type="secondary"
                    onClick={() => router.actions.push(urls.featureManagement())}
                >
                    Cancel
                </LemonButton>
                <LemonButton type="primary" data-attr="save-feature-flag" htmlType="submit" form="feature-creation">
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}

function FeatureManagementMetric({ insight, onDelete }: { insight: InsightModel; onDelete: () => void }): JSX.Element {
    return (
        <div>
            <div className="flex items-center gap-2">
                <span>{insight.name}</span>

                <Link to={urls.insightView(insight.short_id)}>
                    <LemonButton type="primary" icon={<IconExternal />}>
                        View metric
                    </LemonButton>
                </Link>

                <LemonButton type="secondary" icon={<IconTrash />} onClick={onDelete} />
            </div>
        </div>
    )
}

function FeatureMetricModal({
    isOpen,
    onChange,
    onClose,
}: {
    isOpen: boolean
    onChange: (metric: InsightModel) => void
    onClose: () => void
}): JSX.Element {
    const { experiment, experimentLoading } = useValues(experimentLogic({ experimentId }))
    const { updateExperiment } = useActions(experimentLogic({ experimentId }))

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1000}
            title="Change feature metric"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton form="edit-experiment-exposure-form" type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        onClick={() => {
                            updateExperiment({
                                metrics: experiment.metrics,
                            })
                        }}
                        type="primary"
                        loading={experimentLoading}
                        data-attr="create-annotation-submit"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <PrimaryGoalTrendsExposure />
        </LemonModal>
    )
}

function FeatureMetricPicker({ onChange }: { onChange: (something: any) => void }): JSX.Element {
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    if (!editingPrimaryMetricIndex && editingPrimaryMetricIndex !== 0) {
        return <></>
    }

    const metricIdx = editingPrimaryMetricIndex
    const currentMetric = experiment.metrics[metricIdx] as ExperimentTrendsQuery

    return (
        <>
            <ActionFilter
                bordered
                filters={queryNodeToFilter(currentMetric.exposure_query as InsightQueryNode)}
                setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                    const series = actionsAndEventsToSeries(
                        { actions, events, data_warehouse } as any,
                        true,
                        MathAvailability.All
                    )

                    setTrendsExposureMetric({
                        metricIdx,
                        series,
                    })
                }}
                typeKey="experiment-metric"
                buttonCopy="Add graph series"
                showSeriesIndicator={true}
                entitiesLimit={1}
                showNumericalPropsOnly={true}
                {...commonActionFilterProps}
            />
            <div className="mt-4 space-y-4">
                <TestAccountFilterSwitch
                    checked={hasFilters ? !!currentMetric.exposure_query?.filterTestAccounts : false}
                    onChange={(checked: boolean) => {
                        setTrendsExposureMetric({
                            metricIdx,
                            filterTestAccounts: checked,
                        })
                    }}
                    fullWidth
                />
            </div>
            <div className="mt-4">
                <Query
                    query={{
                        kind: NodeKind.InsightVizNode,
                        source: currentMetric.exposure_query,
                        showTable: false,
                        showLastComputation: true,
                        showLastComputationRefresh: false,
                    }}
                    readOnly
                />
            </div>
        </>
    )
}
