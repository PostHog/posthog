import { Card, Col, Collapse, Popconfirm, Progress, Row, Skeleton, Tag, Tooltip } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useEffect, useState } from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { ChartDisplayType, FilterType, FunnelStep, FunnelVizType, InsightType } from '~/types'
import './Experiment.scss'
import { experimentLogic, ExperimentLogicProps } from './experimentLogic'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { IconDelete, IconPlusMini } from 'lib/components/icons'
import { InfoCircleOutlined, CloseOutlined } from '@ant-design/icons'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { dayjs } from 'lib/dayjs'
import { FunnelLayout } from 'lib/constants'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { capitalizeFirstLetter, convertPropertyGroupToProperties, humanFriendlyNumber } from 'lib/utils'
import { SecondaryMetrics } from './SecondaryMetrics'
import { getSeriesColor } from 'lib/colors'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { ExperimentPreview } from './ExperimentPreview'
import { ExperimentImplementationDetails } from './ExperimentImplementationDetails'
import { LemonButton } from 'lib/components/LemonButton'
import { router } from 'kea-router'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonDivider, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'
import { NotFound } from 'lib/components/NotFound'
import { AlertMessage } from 'lib/components/AlertMessage'
import { Form, Group } from 'kea-forms'
import { Field } from 'lib/forms/Field'

export const scene: SceneExport = {
    component: Experiment,
    logic: experimentLogic,
    paramsToProps: ({ params: { id } }): ExperimentLogicProps => ({
        experimentId: id === 'new' ? 'new' : parseInt(id),
    }),
}

export function Experiment(): JSX.Element {
    const {
        experimentId,
        experiment,
        experimentInsightId,
        minimumSampleSizePerVariant,
        recommendedExposureForCountData,
        variants,
        experimentResults,
        countDataForVariant,
        editingExistingExperiment,
        experimentInsightType,
        experimentResultsLoading,
        experimentLoading,
        areResultsSignificant,
        conversionRateForVariant,
        getIndexForVariant,
        significanceBannerDetails,
        areTrendResultsConfusing,
        taxonomicGroupTypesForSelection,
        groupTypes,
        aggregationLabel,
        // secondaryMetricResults,
        // secondaryMetricResultsLoading,
        experimentResultCalculationError,
        flagImplementationWarning,
        flagAvailabilityWarning,
        props,
        sortedExperimentResultVariants,
    } = useValues(experimentLogic)
    const {
        launchExperiment,
        setFilters,
        setEditExperiment,
        endExperiment,
        addExperimentGroup,
        updateExperiment,
        removeExperimentGroup,
        createNewExperimentInsight,
        archiveExperiment,
        resetRunningExperiment,
        loadExperiment,
        setExposureAndSampleSize,
        setExperimentValue,
    } = useActions(experimentLogic)

    const [showWarning, setShowWarning] = useState(true)

    const { insightProps } = useValues(
        insightLogic({
            dashboardItemId: experimentInsightId,
        })
    )
    const {
        isStepsEmpty,
        filterSteps,
        filters: funnelsFilters,
        results,
        conversionMetrics,
    } = useValues(funnelLogic(insightProps))
    const { filters: trendsFilters, results: trendResults } = useValues(trendsLogic(insightProps))

    // Parameters for creating experiment
    const conversionRate = conversionMetrics.totalRate * 100
    const sampleSizePerVariant = minimumSampleSizePerVariant(conversionRate)
    const sampleSize = sampleSizePerVariant * variants.length
    const trendCount = trendResults[0]?.count
    const entrants = results?.[0]?.count
    const exposure = recommendedExposureForCountData(trendCount)
    const secondaryColumnSpan = Math.floor(24 / (variants.length + 2)) // +2 for the names column

    useEffect(() => {
        setExposureAndSampleSize(exposure, sampleSize)
    }, [exposure, sampleSize])

    // Parameters for experiment results
    // don't use creation variables in results
    const funnelResultsPersonsTotal =
        experimentInsightType === InsightType.FUNNELS && experimentResults?.insight
            ? (experimentResults.insight as FunnelStep[][]).reduce(
                  (sum: number, variantResult: FunnelStep[]) => variantResult[0]?.count + sum,
                  0
              )
            : 0

    const experimentProgressPercent =
        experimentInsightType === InsightType.FUNNELS
            ? ((funnelResultsPersonsTotal || 0) / (experiment?.parameters?.recommended_sample_size || 1)) * 100
            : (dayjs().diff(experiment?.start_date, 'day') / (experiment?.parameters?.recommended_running_time || 1)) *
              100

    const statusColors = { running: 'green', draft: 'default', complete: 'purple' }
    const status = (): string => {
        if (!experiment?.start_date) {
            return 'draft'
        } else if (!experiment?.end_date) {
            return 'running'
        }
        return 'complete'
    }

    const maxVariants = 10

    const variantLabelColors = [
        { background: '#35416b', color: '#fff' },
        { background: '#C278CE66', color: '#35416B' },
        { background: '#FFE6AE', color: '#35416B' },
        { background: '#8DA9E74D', color: '#35416B' },
    ]

    if (experimentLoading) {
        return <Skeleton active />
    }

    if (!experiment && experimentId !== 'new') {
        return <NotFound object="experiment" />
    }

    return (
        <>
            {experimentId === 'new' || editingExistingExperiment ? (
                <>
                    <Form
                        logic={experimentLogic}
                        formKey="experiment"
                        props={props}
                        id="experiment-form"
                        enableFormOnSubmit
                        className="space-y-4 experiment-form"
                    >
                        <PageHeader
                            title={editingExistingExperiment ? 'Edit experiment' : 'New experiment'}
                            buttons={
                                <div className="flex items-center gap-2">
                                    <LemonButton
                                        data-attr="cancel-experiment"
                                        type="secondary"
                                        onClick={() => {
                                            if (editingExistingExperiment) {
                                                setEditExperiment(false)
                                                loadExperiment()
                                            } else {
                                                router.actions.push(urls.experiments())
                                            }
                                        }}
                                        disabled={experimentLoading}
                                    >
                                        Cancel
                                    </LemonButton>
                                    <LemonButton
                                        type="primary"
                                        data-attr="save-experiment"
                                        htmlType="submit"
                                        loading={experimentLoading}
                                        disabled={experimentLoading}
                                    >
                                        Save
                                    </LemonButton>
                                </div>
                            }
                        />
                        <LemonDivider />

                        <BindLogic logic={insightLogic} props={insightProps}>
                            <>
                                <div className="flex flex-col gap-2" style={{ maxWidth: '50%' }}>
                                    <Field name="name" label="Name">
                                        <LemonInput data-attr="experiment-name" />
                                    </Field>
                                    <Field name="feature_flag_key" label="Feature flag key">
                                        <LemonInput
                                            data-attr="experiment-feature-flag-key"
                                            disabled={editingExistingExperiment}
                                        />
                                    </Field>
                                    <Field
                                        name="description"
                                        label={
                                            <div>
                                                Description <span className="text-muted">(optional)</span>
                                            </div>
                                        }
                                    >
                                        <LemonTextArea
                                            data-attr="experiment-description"
                                            className="ph-ignore-input"
                                            placeholder="Adding a helpful description can ensure others know what this experiment is about."
                                        />
                                    </Field>
                                    {experiment.parameters.feature_flag_variants && (
                                        <Col>
                                            <label>
                                                <b>Experiment variants</b>
                                            </label>
                                            <div className="text-muted">
                                                Participants are divided into variant groups evenly. All experiments
                                                must consist of a control group and at least one test group. Experiments
                                                may have at most 3 test groups. Variant names can only contain letters,
                                                numbers, hyphens, and underscores.
                                            </div>
                                            <Col className="variants">
                                                {experiment.parameters.feature_flag_variants?.map((variant, index) => (
                                                    <Group
                                                        key={index}
                                                        name={['parameters', 'feature_flag_variants', index]}
                                                    >
                                                        <Row
                                                            key={`${variant}-${index}`}
                                                            className={`feature-flag-variant ${
                                                                index === 0
                                                                    ? 'border-t'
                                                                    : index >= maxVariants
                                                                    ? 'border-b'
                                                                    : ''
                                                            }`}
                                                        >
                                                            <div
                                                                className="variant-label"
                                                                style={
                                                                    index === 0
                                                                        ? { ...variantLabelColors[index] }
                                                                        : {
                                                                              ...variantLabelColors[(index % 3) + 1],
                                                                          }
                                                                }
                                                            >
                                                                {index === 0 ? 'Control' : 'Test'}
                                                            </div>
                                                            <Field name="key" className="extend-variant-fully">
                                                                <LemonInput
                                                                    disabled={index === 0 || experimentId !== 'new'}
                                                                    data-attr="experiment-variant-key"
                                                                    data-key-index={index.toString()}
                                                                    className="ph-ignore-input"
                                                                    fullWidth
                                                                    placeholder={`example-variant-${index + 1}`}
                                                                    autoComplete="off"
                                                                    autoCapitalize="off"
                                                                    autoCorrect="off"
                                                                    spellCheck={false}
                                                                />
                                                            </Field>

                                                            <div className="float-right">
                                                                {experimentId === 'new' &&
                                                                    !(index === 0 || index === 1) && (
                                                                        <Tooltip
                                                                            title="Delete this variant"
                                                                            placement="bottomLeft"
                                                                        >
                                                                            <LemonButton
                                                                                status="primary-alt"
                                                                                size="small"
                                                                                icon={<IconDelete />}
                                                                                onClick={() =>
                                                                                    removeExperimentGroup(index)
                                                                                }
                                                                            />
                                                                        </Tooltip>
                                                                    )}
                                                            </div>
                                                        </Row>
                                                    </Group>
                                                ))}

                                                {(experiment.parameters.feature_flag_variants.length ?? 0) <
                                                    maxVariants &&
                                                    experimentId === 'new' && (
                                                        <div className="feature-flag-variant border-b">
                                                            <LemonButton
                                                                onClick={() => addExperimentGroup()}
                                                                icon={<IconPlusMini />}
                                                            >
                                                                Add test variant
                                                            </LemonButton>
                                                        </div>
                                                    )}
                                            </Col>
                                        </Col>
                                    )}
                                </div>
                                <Row className="person-selection">
                                    <Col span={12}>
                                        <div className="mb-2">
                                            <strong>Select participants</strong>
                                        </div>
                                        <div className="text-muted">
                                            Select the entities who will participate in this experiment. If no filters
                                            are set, 100% of participants will be targeted.
                                        </div>
                                        <div className="mt-4 mb-2">
                                            <strong>Participant type</strong>
                                        </div>
                                        <LemonSelect
                                            value={
                                                experiment.filters.aggregation_group_type_index != undefined
                                                    ? experiment.filters.aggregation_group_type_index
                                                    : -1
                                            }
                                            data-attr="participant-aggregation-filter"
                                            dropdownMatchSelectWidth={false}
                                            onChange={(rawGroupTypeIndex) => {
                                                const groupTypeIndex =
                                                    rawGroupTypeIndex !== -1 ? rawGroupTypeIndex : undefined

                                                setFilters({
                                                    properties: [],
                                                    aggregation_group_type_index: groupTypeIndex ?? undefined,
                                                })
                                                setExperimentValue('filters', {
                                                    ...experiment.filters,
                                                    aggregation_group_type_index: groupTypeIndex,
                                                    // :TRICKY: We reset property filters after changing what you're aggregating by.
                                                    properties: [],
                                                })
                                            }}
                                            options={[
                                                { value: -1, label: 'Persons' },
                                                ...groupTypes.map((groupType) => ({
                                                    value: groupType.group_type_index,
                                                    label: capitalizeFirstLetter(
                                                        aggregationLabel(groupType.group_type_index).plural
                                                    ),
                                                })),
                                            ]}
                                        />
                                        <div className="mt-4 mb-2">
                                            <strong>Filters</strong>
                                        </div>
                                        <div className="mb-4">
                                            <PropertyFilters
                                                pageKey={`experiment-participants-property-${JSON.stringify(
                                                    experiment.filters
                                                )}`}
                                                propertyFilters={convertPropertyGroupToProperties(
                                                    experiment.filters.properties
                                                )}
                                                onChange={(anyProperties) => {
                                                    setFilters({
                                                        properties: anyProperties.filter(isValidPropertyFilter),
                                                    })
                                                    setExperimentValue('filters', {
                                                        ...experiment.filters,
                                                        properties: anyProperties.filter(isValidPropertyFilter),
                                                    })
                                                }}
                                                taxonomicGroupTypes={taxonomicGroupTypesForSelection}
                                            />
                                        </div>
                                        {flagAvailabilityWarning && (
                                            <AlertMessage type="info" className="mt-3 mb-3">
                                                These properties aren't immediately available on first page load for
                                                unidentified persons. This experiment requires that at least one event
                                                is sent prior to becoming available to your product or website.{' '}
                                                <a
                                                    href="https://posthog.com/docs/integrate/client/js#bootstrapping-flags"
                                                    target="_blank"
                                                >
                                                    {' '}
                                                    Learn more about how to make feature flags available instantly.
                                                </a>
                                            </AlertMessage>
                                        )}
                                        <div className="mt-4 mb-2">
                                            <strong>Advanced Options</strong>
                                        </div>
                                        <div className="mb-4">
                                            For more advanced options like changing the rollout percentage and
                                            persisting feature flags, you can{' '}
                                            {experimentId === 'new' ? (
                                                'change settings on the feature flag after creation.'
                                            ) : (
                                                <Link
                                                    to={
                                                        experiment.feature_flag
                                                            ? urls.featureFlag(experiment.feature_flag)
                                                            : undefined
                                                    }
                                                >
                                                    change settings on the feature flag.
                                                </Link>
                                            )}
                                        </div>
                                    </Col>
                                </Row>

                                <Row className="metrics-selection">
                                    <Col span={12}>
                                        <div className="mb-2" data-attr="experiment-goal-type">
                                            <b>Goal type</b>
                                            <div className="text-muted">
                                                {experimentInsightType === InsightType.TRENDS
                                                    ? 'Track counts of a specific event or action'
                                                    : 'Track how many persons complete a sequence of actions and or events'}
                                            </div>
                                        </div>
                                        <LemonSelect
                                            value={experimentInsightType}
                                            onChange={(val) => {
                                                val &&
                                                    createNewExperimentInsight({
                                                        insight: val,
                                                        properties: experiment?.filters?.properties,
                                                    })
                                            }}
                                            dropdownMatchSelectWidth={false}
                                            options={[
                                                { value: InsightType.TRENDS, label: 'Trend' },
                                                { value: InsightType.FUNNELS, label: 'Conversion funnel' },
                                            ]}
                                        />
                                        <div className="my-4">
                                            <b>Experiment goal</b>
                                            {experimentInsightType === InsightType.TRENDS && (
                                                <div className="text-muted">
                                                    Trend-based experiments can have at most one graph series. This
                                                    metric is used to track the progress of your experiment.
                                                </div>
                                            )}
                                        </div>
                                        {flagImplementationWarning && (
                                            <AlertMessage type="info" className="mt-3 mb-3">
                                                We can't detect any feature flag information for this target metric.
                                                Ensure that you're using the latest PostHog client libraries, and make
                                                sure you manually send feature flag information for server-side
                                                libraries if necessary.{' '}
                                                <a
                                                    href="https://posthog.com/docs/integrate/server/python#capture"
                                                    target="_blank"
                                                >
                                                    {' '}
                                                    Read the docs for how to do this for server-side libraries.
                                                </a>
                                            </AlertMessage>
                                        )}
                                        {experimentInsightType === InsightType.FUNNELS && (
                                            <ActionFilter
                                                bordered
                                                filters={funnelsFilters}
                                                setFilters={(payload) => {
                                                    setFilters(payload)
                                                    setExperimentValue('filters', {
                                                        ...experiment.filters,
                                                        ...payload,
                                                    })
                                                }}
                                                typeKey={`experiment-funnel-goal-${JSON.stringify(experiment.filters)}`}
                                                mathAvailability={MathAvailability.None}
                                                hideDeleteBtn={filterSteps.length === 1}
                                                buttonCopy="Add funnel step"
                                                showSeriesIndicator={!isStepsEmpty}
                                                seriesIndicatorType="numeric"
                                                sortable
                                                showNestedArrow={true}
                                                propertiesTaxonomicGroupTypes={[
                                                    TaxonomicFilterGroupType.EventProperties,
                                                    TaxonomicFilterGroupType.PersonProperties,
                                                    TaxonomicFilterGroupType.EventFeatureFlags,
                                                    TaxonomicFilterGroupType.Cohorts,
                                                    TaxonomicFilterGroupType.Elements,
                                                ]}
                                            />
                                        )}
                                        {experimentInsightType === InsightType.TRENDS && (
                                            <ActionFilter
                                                bordered
                                                filters={trendsFilters}
                                                setFilters={(payload: Partial<FilterType>) => {
                                                    setFilters(payload)
                                                    setExperimentValue('filters', {
                                                        ...experiment.filters,
                                                        ...payload,
                                                    })
                                                }}
                                                typeKey={`experiment-trends-goal-${JSON.stringify(experiment.filters)}`}
                                                buttonCopy="Add graph series"
                                                showSeriesIndicator
                                                entitiesLimit={1}
                                                hideDeleteBtn
                                                propertiesTaxonomicGroupTypes={[
                                                    TaxonomicFilterGroupType.EventProperties,
                                                    TaxonomicFilterGroupType.PersonProperties,
                                                    TaxonomicFilterGroupType.EventFeatureFlags,
                                                    TaxonomicFilterGroupType.Cohorts,
                                                    TaxonomicFilterGroupType.Elements,
                                                ]}
                                            />
                                        )}
                                    </Col>
                                    <Col span={12} className="pl-4">
                                        <div className="card-secondary mb-4" data-attr="experiment-preview">
                                            Goal preview
                                        </div>
                                        <InsightContainer
                                            disableHeader={experimentInsightType === InsightType.TRENDS}
                                            disableTable={true}
                                            disableCorrelationTable={true}
                                        />
                                    </Col>
                                </Row>
                                <Field name="secondary_metrics">
                                    {({ value, onChange }) => (
                                        <Row className="secondary-metrics">
                                            <div className="flex flex-col">
                                                <div>
                                                    <b>Secondary metrics</b>
                                                    <span className="text-muted ml-2">(optional)</span>
                                                </div>
                                                <div className="text-muted" style={{ marginTop: 4 }}>
                                                    Use secondary metrics to monitor metrics related to your experiment
                                                    goal. You can add up to three secondary metrics.{' '}
                                                </div>
                                                {JSON.stringify(value)}
                                                <SecondaryMetrics
                                                    onMetricsChange={(val) => {
                                                        onChange(val)
                                                        console.log('incoming changed values: ', val)
                                                    }}
                                                    initialMetrics={value}
                                                    experimentId={experiment.id}
                                                />
                                            </div>
                                        </Row>
                                    )}
                                </Field>
                                <Card className="experiment-preview">
                                    <ExperimentPreview
                                        experimentId={experiment.id}
                                        trendCount={trendCount}
                                        trendExposure={exposure}
                                        funnelSampleSize={sampleSize}
                                        funnelEntrants={entrants}
                                        funnelConversionRate={conversionRate}
                                    />
                                </Card>
                                <Row />
                            </>
                        </BindLogic>
                        <div className="flex items-center gap-2 justify-end">
                            <LemonButton
                                data-attr="cancel-experiment"
                                type="secondary"
                                onClick={() => {
                                    if (editingExistingExperiment) {
                                        setEditExperiment(false)
                                        loadExperiment()
                                    } else {
                                        router.actions.push(urls.experiments())
                                    }
                                }}
                                disabled={experimentLoading}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                data-attr="save-experiment"
                                htmlType="submit"
                                loading={experimentLoading}
                                disabled={experimentLoading}
                            >
                                Save
                            </LemonButton>
                        </div>
                    </Form>
                </>
            ) : experiment ? (
                <div className="view-experiment">
                    <Row className="draft-header">
                        <Row justify="space-between" align="middle" className="w-full pb-4">
                            <Col>
                                <Row>
                                    <PageHeader
                                        style={{ paddingRight: 8 }}
                                        title={`${experiment?.name}`}
                                        buttons={
                                            <>
                                                <CopyToClipboardInline
                                                    explicitValue={experiment.feature_flag_key}
                                                    iconStyle={{ color: 'var(--muted-alt)' }}
                                                >
                                                    <span className="text-muted">{experiment.feature_flag_key}</span>
                                                </CopyToClipboardInline>
                                                <Tag style={{ alignSelf: 'center' }} color={statusColors[status()]}>
                                                    <b className="uppercase">{status()}</b>
                                                </Tag>
                                                {experimentResults && experiment.end_date && (
                                                    <Tag
                                                        style={{ alignSelf: 'center' }}
                                                        color={areResultsSignificant ? 'green' : 'geekblue'}
                                                    >
                                                        <b className="uppercase">
                                                            {areResultsSignificant
                                                                ? 'Significant Results'
                                                                : 'Results not significant'}
                                                        </b>
                                                    </Tag>
                                                )}
                                            </>
                                        }
                                    />
                                </Row>
                                <span className="exp-description">
                                    {experiment.start_date ? (
                                        <EditableField
                                            multiline
                                            name="description"
                                            value={experiment.description || ''}
                                            placeholder="Description (optional)"
                                            onSave={(value) => updateExperiment({ description: value })}
                                            maxLength={400} // Sync with Experiment model
                                            data-attr="experiment-description"
                                            compactButtons
                                        />
                                    ) : (
                                        <>{experiment.description || 'There is no description for this experiment.'}</>
                                    )}
                                </span>
                            </Col>
                            {experiment && !experiment.start_date && (
                                <div className="flex items-center">
                                    <LemonButton
                                        type="secondary"
                                        className="mr-2"
                                        onClick={() => setEditExperiment(true)}
                                    >
                                        Edit
                                    </LemonButton>
                                    <LemonButton type="primary" onClick={() => launchExperiment()}>
                                        Launch
                                    </LemonButton>
                                </div>
                            )}
                            {experiment && experiment.start_date && !experiment.end_date && (
                                <div className="flex flex-row gap-2">
                                    <Popconfirm
                                        placement="topLeft"
                                        title={
                                            <div>
                                                Reset this experiment and go back to draft mode?
                                                <div className="text-sm text-muted">
                                                    All collected data so far will be discarded.
                                                </div>
                                            </div>
                                        }
                                        onConfirm={() => resetRunningExperiment()}
                                    >
                                        <LemonButton type="secondary" status="primary">
                                            Reset
                                        </LemonButton>
                                    </Popconfirm>
                                    <LemonButton type="secondary" status="danger" onClick={() => endExperiment()}>
                                        Stop
                                    </LemonButton>
                                </div>
                            )}
                            {experiment?.end_date &&
                                dayjs().isSameOrAfter(dayjs(experiment.end_date), 'day') &&
                                !experiment.archived && (
                                    <LemonButton type="secondary" status="danger" onClick={() => archiveExperiment()}>
                                        <b>Archive</b>
                                    </LemonButton>
                                )}
                        </Row>
                    </Row>
                    <Row>
                        {showWarning && experimentResults && areResultsSignificant && !experiment.end_date && (
                            <Row align="middle" className="significant-results">
                                <Col span={20} style={{ fontWeight: 500, color: '#497342' }}>
                                    <div>
                                        Experiment results are significant.{' '}
                                        {experiment.end_date
                                            ? ''
                                            : 'You can end your experiment now or let it run until complete.'}
                                    </div>
                                </Col>
                                <Col span={4}>
                                    {experiment.end_date ? (
                                        <CloseOutlined className="close-button" onClick={() => setShowWarning(false)} />
                                    ) : (
                                        <LemonButton type="primary" onClick={() => endExperiment()}>
                                            End experiment
                                        </LemonButton>
                                    )}
                                </Col>
                            </Row>
                        )}
                        {showWarning && experimentResults && !areResultsSignificant && !experiment.end_date && (
                            <Row align="top" className="not-significant-results">
                                <Col span={23} style={{ fontWeight: 500, color: '#2D2D2D' }}>
                                    <strong>Your results are not statistically significant</strong>.{' '}
                                    {significanceBannerDetails}{' '}
                                    {experiment?.end_date ? '' : "We don't recommend ending this experiment yet."} See
                                    our{' '}
                                    <a href="https://posthog.com/docs/user-guides/experimentation#funnel-experiment-calculations">
                                        {' '}
                                        experimentation guide{' '}
                                    </a>
                                    for more information.{' '}
                                </Col>
                                <Col span={1}>
                                    <CloseOutlined className="close-button" onClick={() => setShowWarning(false)} />
                                </Col>
                            </Row>
                        )}
                        {showWarning && experiment.end_date && (
                            <Row align="top" className="feature-flag-mods">
                                <Col span={23} style={{ fontWeight: 500 }}>
                                    <strong>Your experiment is complete, but the feature flag is still enabled.</strong>{' '}
                                    We recommend removing the feature flag from your code completely, instead of relying
                                    on this distribution.{' '}
                                    <Link
                                        to={
                                            experiment.feature_flag
                                                ? urls.featureFlag(experiment.feature_flag)
                                                : undefined
                                        }
                                    >
                                        <b>Adjust feature flag distribution</b>
                                    </Link>
                                </Col>
                                <Col span={1}>
                                    <CloseOutlined className="close-button" onClick={() => setShowWarning(false)} />
                                </Col>
                            </Row>
                        )}
                    </Row>
                    <Row>
                        <Collapse className="w-full" defaultActiveKey="experiment-details">
                            <Collapse.Panel header={<b>Experiment details</b>} key="experiment-details">
                                <Row>
                                    <Col span={experiment?.start_date ? 12 : 24}>
                                        <ExperimentPreview
                                            experimentId={experiment.id}
                                            trendCount={trendCount}
                                            trendExposure={experiment?.parameters.recommended_running_time}
                                            funnelSampleSize={experiment?.parameters.recommended_sample_size}
                                            funnelConversionRate={conversionRate}
                                            funnelEntrants={
                                                experiment?.start_date ? funnelResultsPersonsTotal : entrants
                                            }
                                        />
                                    </Col>
                                    {!experimentResultsLoading && !experimentResults && experiment.start_date && (
                                        <Col span={12}>
                                            <ExperimentImplementationDetails experiment={experiment} />
                                        </Col>
                                    )}
                                    {experimentResults && (
                                        <Col span={12} className="mt-4">
                                            <div className="mb-2">
                                                <b>Experiment progress</b>
                                            </div>
                                            <Progress
                                                strokeWidth={20}
                                                showInfo={false}
                                                percent={experimentProgressPercent}
                                                strokeColor="var(--success)"
                                            />
                                            {experimentInsightType === InsightType.TRENDS && experiment.start_date && (
                                                <Row justify="space-between" className="mt-2">
                                                    {experiment.end_date ? (
                                                        <div>
                                                            Ran for{' '}
                                                            <b>
                                                                {dayjs(experiment.end_date).diff(
                                                                    experiment.start_date,
                                                                    'day'
                                                                )}
                                                            </b>{' '}
                                                            days
                                                        </div>
                                                    ) : (
                                                        <div>
                                                            <b>{dayjs().diff(experiment.start_date, 'day')}</b> days
                                                            running
                                                        </div>
                                                    )}
                                                    <div>
                                                        Goal:{' '}
                                                        <b>
                                                            {experiment?.parameters?.recommended_running_time ??
                                                                'Unknown'}
                                                        </b>{' '}
                                                        days
                                                    </div>
                                                </Row>
                                            )}
                                            {experimentInsightType === InsightType.FUNNELS && (
                                                <Row justify="space-between" className="mt-2">
                                                    {experiment.end_date ? (
                                                        <div>
                                                            Saw <b>{humanFriendlyNumber(funnelResultsPersonsTotal)}</b>{' '}
                                                            participants
                                                        </div>
                                                    ) : (
                                                        <div>
                                                            <b>{humanFriendlyNumber(funnelResultsPersonsTotal)}</b>{' '}
                                                            participants seen
                                                        </div>
                                                    )}
                                                    <div>
                                                        Goal:{' '}
                                                        <b>
                                                            {humanFriendlyNumber(
                                                                experiment?.parameters?.recommended_sample_size || 0
                                                            )}
                                                        </b>{' '}
                                                        participants
                                                    </div>
                                                </Row>
                                            )}
                                        </Col>
                                    )}
                                    {/*  TODO: Need a way to add them to a new new running experiment */}
                                    {experiment.secondary_metrics?.length >= 0 && (
                                        <Col
                                            className="secondary-progress"
                                            span={
                                                experiment?.start_date &&
                                                (experiment?.parameters?.feature_flag_variants?.length || 0) <= 5
                                                    ? 12
                                                    : 24
                                            }
                                        >
                                            <SecondaryMetrics
                                                experimentId={experiment.id}
                                                onMetricsChange={(metrics) =>
                                                    updateExperiment({
                                                        secondary_metrics: metrics,
                                                    })
                                                }
                                                initialMetrics={experiment.secondary_metrics}
                                                // experimentResults={experimentResults}
                                            />
                                        </Col>
                                    )}
                                </Row>
                            </Collapse.Panel>
                        </Collapse>
                        {!experiment?.start_date && (
                            <div className="mt-4 w-full">
                                <ExperimentImplementationDetails experiment={experiment} />
                            </div>
                        )}
                    </Row>
                    <div className="experiment-result">
                        {experimentResults ? (
                            (experiment?.parameters?.feature_flag_variants?.length || 0) > 4 ? (
                                <>
                                    <Row
                                        className="border-t"
                                        justify="space-between"
                                        style={{
                                            paddingTop: 8,
                                            paddingBottom: 8,
                                        }}
                                    >
                                        <Col span={2 * secondaryColumnSpan}>Variant</Col>
                                        {sortedExperimentResultVariants.map((variant, idx) => (
                                            <Col
                                                key={idx}
                                                span={secondaryColumnSpan}
                                                style={{
                                                    color: getSeriesColor(
                                                        getIndexForVariant(variant, experimentInsightType)
                                                    ),
                                                }}
                                            >
                                                <b>{capitalizeFirstLetter(variant)}</b>
                                            </Col>
                                        ))}
                                    </Row>
                                    <Row
                                        className="border-t"
                                        justify="space-between"
                                        style={{
                                            paddingTop: 8,
                                            paddingBottom: 8,
                                        }}
                                    >
                                        <Col span={2 * secondaryColumnSpan}>
                                            {experimentInsightType === InsightType.TRENDS ? 'Count' : 'Conversion Rate'}
                                        </Col>
                                        {sortedExperimentResultVariants.map((variant, idx) => (
                                            <Col key={idx} span={secondaryColumnSpan}>
                                                {experimentInsightType === InsightType.TRENDS
                                                    ? countDataForVariant(variant)
                                                    : `${conversionRateForVariant(variant)}%`}
                                            </Col>
                                        ))}
                                    </Row>
                                    <Row
                                        className="border-t"
                                        justify="space-between"
                                        style={{
                                            paddingTop: 8,
                                            paddingBottom: 8,
                                        }}
                                    >
                                        <Col span={2 * secondaryColumnSpan}>Probability to be the best</Col>
                                        {sortedExperimentResultVariants.map((variant, idx) => (
                                            <Col key={idx} span={secondaryColumnSpan}>
                                                <b>
                                                    {experimentResults.probability[variant]
                                                        ? `${(experimentResults.probability[variant] * 100).toFixed(
                                                              1
                                                          )}%`
                                                        : '--'}
                                                </b>
                                            </Col>
                                        ))}
                                    </Row>
                                </>
                            ) : (
                                <Row justify="space-around" style={{ flexFlow: 'nowrap' }}>
                                    {
                                        //sort by decreasing probability
                                        Object.keys(experimentResults.probability)
                                            .sort(
                                                (a, b) =>
                                                    experimentResults.probability[b] - experimentResults.probability[a]
                                            )
                                            .map((variant, idx) => (
                                                <Col key={idx} className="pr-4">
                                                    <div>
                                                        <b>{capitalizeFirstLetter(variant)}</b>
                                                    </div>
                                                    {experimentInsightType === InsightType.TRENDS ? (
                                                        <Row>
                                                            <b style={{ paddingRight: 4 }}>
                                                                <Row>
                                                                    {'action' in experimentResults.insight[0] && (
                                                                        <EntityFilterInfo
                                                                            filter={experimentResults.insight[0].action}
                                                                        />
                                                                    )}
                                                                    <span style={{ paddingLeft: 4 }}>count:</span>
                                                                </Row>
                                                            </b>{' '}
                                                            {countDataForVariant(variant)}{' '}
                                                            {areTrendResultsConfusing && idx === 0 && (
                                                                <Tooltip
                                                                    placement="right"
                                                                    title="It might seem confusing that the best variant has lower absolute count, but this can happen when fewer people are exposed to this variant, so its relative count is higher."
                                                                >
                                                                    <InfoCircleOutlined
                                                                        style={{ padding: '4px 2px' }}
                                                                    />
                                                                </Tooltip>
                                                            )}
                                                        </Row>
                                                    ) : (
                                                        <Row>
                                                            <b style={{ paddingRight: 4 }}>Conversion rate:</b>{' '}
                                                            {conversionRateForVariant(variant)}%
                                                        </Row>
                                                    )}
                                                    <Progress
                                                        percent={Number(
                                                            (experimentResults.probability[variant] * 100).toFixed(1)
                                                        )}
                                                        size="small"
                                                        showInfo={false}
                                                        strokeColor={getSeriesColor(
                                                            getIndexForVariant(variant, experimentInsightType)
                                                        )}
                                                    />
                                                    <div>
                                                        Probability that this variant is the best:{' '}
                                                        <b>
                                                            {(experimentResults.probability[variant] * 100).toFixed(1)}%
                                                        </b>
                                                    </div>
                                                </Col>
                                            ))
                                    }
                                </Row>
                            )
                        ) : (
                            experimentResultsLoading && (
                                <div className="text-center">
                                    <Skeleton active />
                                </div>
                            )
                        )}
                        {experimentResults ? (
                            <BindLogic
                                logic={insightLogic}
                                props={{
                                    dashboardItemId: experimentResults.itemID,
                                    cachedInsight: {
                                        short_id: experimentResults.itemID,
                                        filters: {
                                            ...experimentResults.filters,
                                            insight: experimentInsightType,
                                            ...(experimentInsightType === InsightType.FUNNELS && {
                                                layout: FunnelLayout.vertical,
                                                funnel_viz_type: FunnelVizType.Steps,
                                            }),
                                            ...(experimentInsightType === InsightType.TRENDS && {
                                                display: ChartDisplayType.ActionsLineGraphCumulative,
                                            }),
                                        },
                                        result: experimentResults.insight,
                                        disable_baseline: true,
                                    },
                                    doNotLoad: true,
                                }}
                            >
                                <div className="mt-4">
                                    <InsightContainer
                                        disableHeader={true}
                                        disableCorrelationTable={experimentInsightType === InsightType.FUNNELS}
                                        disableLastComputation={true}
                                    />
                                </div>
                            </BindLogic>
                        ) : (
                            experiment.start_date && (
                                <>
                                    <div className="no-experiment-results">
                                        {!experimentResultsLoading && (
                                            <div className="text-center">
                                                <b>There are no results for this experiment yet.</b>
                                                <div className="text-sm ">
                                                    {!!experimentResultCalculationError &&
                                                        `${experimentResultCalculationError}. `}{' '}
                                                    Wait a bit longer for your users to be exposed to the experiment.
                                                    Double check your feature flag implementation if you're still not
                                                    seeing results.
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                </>
                            )
                        )}
                    </div>
                </div>
            ) : (
                <Skeleton active />
            )}
        </>
    )
}
