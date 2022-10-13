import { Card, Col, Collapse, Input, Progress, Row, Select, Skeleton, Tag, Tooltip } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React, { useState } from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import {
    ChartDisplayType,
    FilterType,
    FunnelStep,
    FunnelVizType,
    InsightType,
    MultivariateFlagVariant,
    PropertyFilter,
} from '~/types'
import './Experiment.scss'
import { experimentLogic, ExperimentLogicProps } from './experimentLogic'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { IconDelete, IconPlusMini } from 'lib/components/icons'
import { CaretDownOutlined, ExclamationCircleFilled, InfoCircleOutlined, CloseOutlined } from '@ant-design/icons'
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
        experimentData,
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
        secondaryMetricResults,
        secondaryMetricResultsLoading,
        experimentResultCalculationError,
        flagImplementationWarning,
        flagAvailabilityWarning,
        experiment,
        props
        // experimentLoading
    } = useValues(experimentLogic)
    const {
        // setNewExperimentData,
        // createExperiment,
        launchExperiment,
        setFilters,
        setEditExperiment,
        endExperiment,
        addExperimentGroup,
        updateExperiment,
        updateExperimentGroup,
        removeExperimentGroup,
        setExperimentInsightType,
        archiveExperiment,
        loadExperiment
    } = useActions(experimentLogic)

    // const [form] = Form.useForm()
    console.log('insight typee', experimentInsightType, experimentInsightId)
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
            ? ((funnelResultsPersonsTotal || 0) / (experimentData?.parameters?.recommended_sample_size || 1)) * 100
            : (dayjs().diff(experimentData?.start_date, 'day') /
                (experimentData?.parameters?.recommended_running_time || 1)) *
            100

    const statusColors = { running: 'green', draft: 'default', complete: 'purple' }
    const status = (): string => {
        if (!experimentData?.start_date) {
            return 'draft'
        } else if (!experimentData?.end_date) {
            return 'running'
        }
        return 'complete'
    }

    const variantLabelColors = [
        { background: '#35416b', color: '#fff' },
        { background: '#C278CE66', color: '#35416B' },
        { background: '#FFE6AE', color: '#35416B' },
        { background: '#8DA9E74D', color: '#35416B' },
    ]

    if (experimentLoading) {
        return <Skeleton active />
    }

    if (!experimentData && experimentId !== 'new') {
        return <NotFound object="experiment" />
    }

    console.log('experiment dataaa', experimentData, props)

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
                                    <Field name="description" label={<div>Description <span className="text-muted">(optional)</span></div>}>
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
                                                must consist of a control group and at least one test group.
                                                Experiments may have at most 3 test groups. Variant names can only
                                                contain letters, numbers, hyphens, and underscores.
                                            </div>
                                            <Col className="variants">
                                                {experiment.parameters.feature_flag_variants?.map((variant, index) =>
                                                    <Group key={index} name={['parameters', 'feature_flag_variants', index]}>
                                                        <Row
                                                            key={`${variant}-${index}`}
                                                            className={`feature-flag-variant ${index === 0
                                                                ? 'border-t'
                                                                : index >= 3
                                                                    ? 'border-b'
                                                                    : ''
                                                                }`}
                                                        >
                                                            <div
                                                                className="variant-label"
                                                                style={{ ...variantLabelColors[index] }}
                                                            >
                                                                {index === 0 ? 'Control' : 'Test'}
                                                            </div>
                                                            <Field name="key">
                                                                <LemonInput
                                                                    disabled={index === 0}
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
                                                                {!(index === 0 || index === 1) && (
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
                                                )
                                                }

                                                {(experiment.parameters.feature_flag_variants.length ?? 0) < 4 && (
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
                                <Field name="filters">
                                    {({ value, onChange }) => (
                                        <>
                                            <Row className="person-selection">
                                                <Col span={12}>
                                                    <div className="mb-2">
                                                        <strong>Select participants</strong>
                                                    </div>
                                                    <div className="text-muted">
                                                        Select the entities who will participate in this experiment. If no
                                                        filters are set, 100% of participants will be targeted.
                                                    </div>
                                                    <div className="mt-4 mb-2">
                                                        <strong>Participant type</strong>
                                                    </div>
                                                    <LemonSelect
                                                        value={value.aggregation_group_type_index != undefined ? value.aggregation_group_type_index : -1}
                                                        data-attr="participant-aggregation-filter"
                                                        dropdownMatchSelectWidth={false}
                                                        onChange={(value) => {
                                                            const groupTypeIndex = value !== -1 ? value : undefined
                                                            if (
                                                                groupTypeIndex !=
                                                                value.aggregation_group_type_index
                                                            ) {
                                                                setFilters({
                                                                    properties: [],
                                                                    aggregation_group_type_index: groupTypeIndex,
                                                                })
                                                                onChange({
                                                                    ...value,
                                                                    filters: {
                                                                        aggregation_group_type_index: groupTypeIndex,
                                                                        // :TRICKY: We reset property filters after changing what you're aggregating by. 
                                                                        properties: []
                                                                    }
                                                                })
                                                                // setNewExperimentData({
                                                                //     filters: {
                                                                //         aggregation_group_type_index: groupTypeIndex,
                                                                //         // :TRICKY: We reset property filters after changing what you're aggregating by.
                                                                //         properties: [],
                                                                //     },
                                                                // })
                                                            }
                                                        }}
                                                        options={[
                                                            { value: -1, label: 'Persons' },
                                                            ...groupTypes.map(groupType => ({ value: groupType.group_type_index, label: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural) }))
                                                        ]}
                                                    />
                                                    <div className="mt-4 mb-2">
                                                        <strong>Filters</strong>
                                                    </div>
                                                    <div className="mb-4">
                                                        <PropertyFilters
                                                            pageKey={'experiment-participants-property'}
                                                            propertyFilters={
                                                                experimentInsightType === InsightType.FUNNELS
                                                                    ? convertPropertyGroupToProperties(
                                                                        funnelsFilters.properties
                                                                    )
                                                                    : convertPropertyGroupToProperties(
                                                                        trendsFilters.properties
                                                                    )
                                                            }
                                                            onChange={(anyProperties) => {
                                                                onChange({ ...value, filters: { properties: anyProperties } })
                                                                // setNewExperimentData({
                                                                //     filters: {
                                                                //         properties: anyProperties as PropertyFilter[],
                                                                //     },
                                                                // })
                                                                setFilters({
                                                                    properties: anyProperties.filter(isValidPropertyFilter),
                                                                })
                                                            }}
                                                            taxonomicGroupTypes={taxonomicGroupTypesForSelection}
                                                        />
                                                    </div>
                                                    {flagAvailabilityWarning && (
                                                        <AlertMessage type="info" className="mt-3 mb-3">
                                                            These properties aren't immediately available on first page load
                                                            for unidentified persons. This experiment requires that at least
                                                            one event is sent prior to becoming available to your product or
                                                            website.{' '}
                                                            <a
                                                                href="https://posthog.com/docs/integrate/client/js#bootstrapping-flags"
                                                                target="_blank"
                                                            >
                                                                {' '}
                                                                Learn more about how to make feature flags available
                                                                instantly.
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
                                                            if (val) {
                                                                setExperimentInsightType(val)
                                                            }
                                                        }}
                                                        dropdownMatchSelectWidth={false}
                                                        options={[{ value: InsightType.TRENDS, label: "Trend" }, { value: InsightType.FUNNELS, label: "Conversion funnel" }]}
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
                                                            Ensure that you're using the latest PostHog client libraries, and
                                                            make sure you manually send feature flag information for server-side
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
                                                                // setNewExperimentData({ filters: payload })
                                                                onChange({ ...value, filters: payload })
                                                                setFilters(payload)
                                                            }}
                                                            typeKey={`experiment-funnel-goal`}
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
                                                                // setNewExperimentData({ filters: payload })
                                                                onChange({ ...value, filters: payload })
                                                                setFilters(payload)
                                                            }}
                                                            typeKey={`experiment-trends`}
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
                                        </>
                                    )}

                                </Field>
                                <Field name="secondary_metrics">
                                    {({ value, onChange }) => (
                                        <Row className="secondary-metrics">
                                            <div className="flex flex-col">
                                                <div>
                                                    <b>Secondary metrics</b>
                                                    <span className="text-muted ml-2">(optional)</span>
                                                </div>
                                                <div className="text-muted" style={{ marginTop: 4 }}>
                                                    Use secondary metrics to monitor metrics related to your
                                                    experiment goal. You can add up to three secondary metrics.{' '}
                                                </div>
                                                <SecondaryMetrics
                                                    onMetricsChange={onChange}
                                                    initialMetrics={value}
                                                />
                                            </div>
                                        </Row>

                                    )}
                                </Field>
                                {/* <Field name="parameters">
                                        {({value, onChange}) => (
                                    <Card className="experiment-preview">
                                        <ExperimentPreview
                                            experiment={experiment}
                                            trendCount={trendCount}
                                            trendExposure={exposure}
                                            funnelSampleSize={sampleSize}
                                            funnelEntrants={entrants}
                                            funnelConversionRate={conversionRate}
                                            onChange={onChange}
                                        />
                                    </Card>
                                        )}
                                </Field> */}
                                <Row>
                                </Row>
                            </>
                        </BindLogic>
                    </Form>
                    {/* <Form
                        name="new-experiment"
                        layout="vertical"
                        className="experiment-form"
                        form={form}
                        onValuesChange={(values) => setNewExperimentData(values)}
                        initialValues={{
                            name: newExperimentData?.name,
                            feature_flag_key: newExperimentData?.feature_flag_key,
                            description: newExperimentData?.description,
                        }}
                        onFinish={() => createExperiment(true, exposure, sampleSize)}
                        requiredMark={false}
                        scrollToFirstError
                    >
                        <div>
                            <BindLogic logic={insightLogic} props={insightProps}>
                                <Row>
                                    <Col span={12} style={{ paddingRight: 24 }}>
                                        <Row className="w-full">
                                            <Form.Item
                                                style={{ marginRight: 16 }}
                                                label="Name"
                                                name="name"
                                                rules={[{ required: true, message: 'You have to enter a name.' }]}
                                            >
                                                <Input data-attr="experiment-name" className="ph-ignore-input" />
                                            </Form.Item>
                                            <Form.Item
                                                style={{ marginBottom: '1rem' }}
                                                label={
                                                    <div>
                                                        Feature flag key{' '}
                                                        <Tooltip title="Enter a unique key. This will create a new feature flag which will be associated with this experiment.">
                                                            <InfoCircleOutlined />
                                                        </Tooltip>
                                                    </div>
                                                }
                                                name="feature_flag_key"
                                                rules={[
                                                    {
                                                        required: true,
                                                        message: 'You have to enter a feature flag key name.',
                                                    },
                                                ]}
                                            >
                                                <Input
                                                    data-attr="experiment-feature-flag-key"
                                                    disabled={editingExistingExperiment}
                                                />
                                            </Form.Item>
                                        </Row>

                                        <Form.Item
                                            label={
                                                <div>
                                                    Description <span className="text-muted">(optional)</span>
                                                </div>
                                            }
                                            name="description"
                                        >
                                            <LemonTextArea
                                                data-attr="experiment-description"
                                                className="ph-ignore-input"
                                                placeholder="Adding a helpful description can ensure others know what this experiment is about."
                                            />
                                        </Form.Item>

                                        {newExperimentData?.parameters?.feature_flag_variants && (
                                            <Col>
                                                <label>
                                                    <b>Experiment variants</b>
                                                </label>
                                                <div className="text-muted">
                                                    Participants are divided into variant groups evenly. All experiments
                                                    must consist of a control group and at least one test group.
                                                    Experiments may have at most 3 test groups. Variant names can only
                                                    contain letters, numbers, hyphens, and underscores.
                                                </div>
                                                <Col className="variants">
                                                    {newExperimentData.parameters.feature_flag_variants.map(
                                                        (variant: MultivariateFlagVariant, idx: number) => (
                                                            <Form
                                                                key={`${variant}-${idx}`}
                                                                initialValues={{
                                                                    key: variant.key,
                                                                }}
                                                                onValuesChange={(changedValues) => {
                                                                    updateExperimentGroup(changedValues, idx)
                                                                }}
                                                            >
                                                                <Row
                                                                    key={`${variant}-${idx}`}
                                                                    className={`feature-flag-variant ${
                                                                        idx === 0
                                                                            ? 'border-t'
                                                                            : idx >= 3
                                                                            ? 'border-b'
                                                                            : ''
                                                                    }`}
                                                                >
                                                                    <div
                                                                        className="variant-label"
                                                                        style={{ ...variantLabelColors[idx] }}
                                                                    >
                                                                        {idx === 0 ? 'Control' : 'Test'}
                                                                    </div>
                                                                    <Form.Item
                                                                        name="key"
                                                                        rules={[
                                                                            {
                                                                                required: true,
                                                                                message: 'Key should not be empty.',
                                                                            },
                                                                            {
                                                                                required: true,
                                                                                pattern: /^([A-z]|[a-z]|[0-9]|-|_)+$/,
                                                                                message: (
                                                                                    <>
                                                                                        <ExclamationCircleFilled
                                                                                            style={{ color: '#F96132' }}
                                                                                        />{' '}
                                                                                        Variant names can only contain
                                                                                        letters, numbers, hyphens, and
                                                                                        underscores.
                                                                                    </>
                                                                                ),
                                                                            },
                                                                        ]}
                                                                        style={{ display: 'contents' }}
                                                                    >
                                                                        <Input
                                                                            disabled={idx === 0}
                                                                            data-attr="feature-flag-variant-key"
                                                                            data-key-index={idx.toString()}
                                                                            className="ph-ignore-input"
                                                                            placeholder={`example-variant-${idx + 1}`}
                                                                            autoComplete="off"
                                                                            autoCapitalize="off"
                                                                            autoCorrect="off"
                                                                            spellCheck={false}
                                                                        />
                                                                    </Form.Item>

                                                                    <div className="float-right">
                                                                        {!(idx === 0 || idx === 1) && (
                                                                            <Tooltip
                                                                                title="Delete this variant"
                                                                                placement="bottomLeft"
                                                                            >
                                                                                <LemonButton
                                                                                    status="primary-alt"
                                                                                    size="small"
                                                                                    icon={<IconDelete />}
                                                                                    onClick={() =>
                                                                                        removeExperimentGroup(idx)
                                                                                    }
                                                                                />
                                                                            </Tooltip>
                                                                        )}
                                                                    </div>
                                                                </Row>
                                                            </Form>
                                                        )
                                                    )}

                                                    {newExperimentData.parameters.feature_flag_variants.length < 4 && (
                                                        <div className="feature-flag-variant border-b">
                                                            <LemonButton
                                                                onClick={() => addExperimentGroup()}
                                                                fullWidth
                                                                icon={<IconPlusMini />}
                                                            >
                                                                Add test variant
                                                            </LemonButton>
                                                        </div>
                                                    )}
                                                </Col>
                                            </Col>
                                        )}

                                        <Row className="person-selection">
                                            <div className="mb-2">
                                                <strong>Select participants</strong>
                                            </div>
                                            <Col>
                                                <div className="text-muted">
                                                    Select the entities who will participate in this experiment. If no
                                                    filters are set, 100% of participants will be targeted.
                                                </div>
                                                <div className="mt-4 mb-2">
                                                    <strong>Participant type</strong>
                                                </div>
                                                <Select
                                                    value={
                                                        newExperimentData?.filters?.aggregation_group_type_index !=
                                                        undefined
                                                            ? newExperimentData.filters.aggregation_group_type_index
                                                            : -1
                                                    }
                                                    onChange={(value) => {
                                                        const groupTypeIndex = value !== -1 ? value : undefined
                                                        if (
                                                            groupTypeIndex !=
                                                            newExperimentData?.filters?.aggregation_group_type_index
                                                        ) {
                                                            setFilters({
                                                                properties: [],
                                                                aggregation_group_type_index: groupTypeIndex,
                                                            })
                                                            setNewExperimentData({
                                                                filters: {
                                                                    aggregation_group_type_index: groupTypeIndex,
                                                                    // :TRICKY: We reset property filters after changing what you're aggregating by.
                                                                    properties: [],
                                                                },
                                                            })
                                                        }
                                                    }}
                                                    data-attr="participant-aggregation-filter"
                                                    dropdownMatchSelectWidth={false}
                                                >
                                                    <Select.Option key={-1} value={-1}>
                                                        Persons
                                                    </Select.Option>
                                                    {groupTypes.map((groupType) => (
                                                        <Select.Option
                                                            key={groupType.group_type_index}
                                                            value={groupType.group_type_index}
                                                        >
                                                            {capitalizeFirstLetter(
                                                                aggregationLabel(groupType.group_type_index).plural
                                                            )}
                                                        </Select.Option>
                                                    ))}
                                                </Select>
                                                <div className="mt-4 mb-2">
                                                    <strong>Filters</strong>
                                                </div>
                                                <div className="mb-4">
                                                    <PropertyFilters
                                                        pageKey={'experiment-participants-property'}
                                                        propertyFilters={
                                                            experimentInsightType === InsightType.FUNNELS
                                                                ? convertPropertyGroupToProperties(
                                                                      funnelsFilters.properties
                                                                  )
                                                                : convertPropertyGroupToProperties(
                                                                      trendsFilters.properties
                                                                  )
                                                        }
                                                        onChange={(anyProperties) => {
                                                            setNewExperimentData({
                                                                filters: {
                                                                    properties: anyProperties as PropertyFilter[],
                                                                },
                                                            })
                                                            setFilters({
                                                                properties: anyProperties.filter(isValidPropertyFilter),
                                                            })
                                                        }}
                                                        taxonomicGroupTypes={taxonomicGroupTypesForSelection}
                                                    />
                                                </div>
                                                {flagAvailabilityWarning && (
                                                    <AlertMessage type="info" className="mt-3 mb-3">
                                                        These properties aren't immediately available on first page load
                                                        for unidentified persons. This experiment requires that at least
                                                        one event is sent prior to becoming available to your product or
                                                        website.{' '}
                                                        <a
                                                            href="https://posthog.com/docs/integrate/client/js#bootstrapping-flags"
                                                            target="_blank"
                                                        >
                                                            {' '}
                                                            Learn more about how to make feature flags available
                                                            instantly.
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
                                                                newExperimentData?.feature_flag
                                                                    ? urls.featureFlag(newExperimentData.feature_flag)
                                                                    : undefined
                                                            }
                                                        >
                                                            change settings on the feature flag.
                                                        </Link>
                                                    )}
                                                </div>
                                            </Col>
                                        </Row>
                                    </Col>

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
                                            <Select
                                                style={{ display: 'flex' }}
                                                value={experimentInsightType}
                                                onChange={setExperimentInsightType}
                                                suffixIcon={<CaretDownOutlined />}
                                                dropdownMatchSelectWidth={false}
                                            >
                                                <Select.Option value={InsightType.TRENDS}>
                                                    <Col>
                                                        <span>
                                                            <b>Trend</b>
                                                        </span>
                                                    </Col>
                                                </Select.Option>
                                                <Select.Option value={InsightType.FUNNELS}>
                                                    <Col>
                                                        <span>
                                                            <b>Conversion funnel</b>
                                                        </span>
                                                    </Col>
                                                </Select.Option>
                                            </Select>
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
                                                    Ensure that you're using the latest PostHog client libraries, and
                                                    make sure you manually send feature flag information for server-side
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
                                                        setNewExperimentData({ filters: payload })
                                                        setFilters(payload)
                                                    }}
                                                    typeKey={`experiment-funnel-goal`}
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
                                                        setNewExperimentData({ filters: payload })
                                                        setFilters(payload)
                                                    }}
                                                    typeKey={`experiment-trends`}
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
                                            <Row className="secondary-metrics">
                                                <div className="flex flex-col">
                                                    <div>
                                                        <b>Secondary metrics</b>
                                                        <span className="text-muted ml-2">(optional)</span>
                                                    </div>
                                                    <div className="text-muted" style={{ marginTop: 4 }}>
                                                        Use secondary metrics to monitor metrics related to your
                                                        experiment goal. You can add up to three secondary metrics.{' '}
                                                    </div>
                                                    <SecondaryMetrics
                                                        onMetricsChange={(metrics) => setSecondaryMetrics(metrics)}
                                                        initialMetrics={parsedSecondaryMetrics}
                                                    />
                                                </div>
                                            </Row>
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
                                </Row>
                                <Row>
                                    <Card className="experiment-preview">
                                        <ExperimentPreview
                                            experiment={newExperimentData}
                                            trendCount={trendCount}
                                            trendExposure={exposure}
                                            funnelSampleSize={sampleSize}
                                            funnelEntrants={entrants}
                                            funnelConversionRate={conversionRate}
                                        />
                                    </Card>
                                </Row>
                            </BindLogic>
                        </div>
                        <LemonButton className="float-right" type="primary" htmlType="submit">
                            Save
                        </LemonButton>
                    </Form> */}
                </>
            ) : experimentData ? (
                <div className="view-experiment">
                    <Row className="draft-header">
                        <Row justify="space-between" align="middle" className="w-full pb-4">
                            <Col>
                                <Row>
                                    <PageHeader
                                        style={{ paddingRight: 8 }}
                                        title={`${experimentData?.name}`}
                                        buttons={
                                            <>
                                                <CopyToClipboardInline
                                                    explicitValue={experimentData.feature_flag_key}
                                                    iconStyle={{ color: 'var(--muted-alt)' }}
                                                >
                                                    <span className="text-muted">
                                                        {experimentData.feature_flag_key}
                                                    </span>
                                                </CopyToClipboardInline>
                                                <Tag style={{ alignSelf: 'center' }} color={statusColors[status()]}>
                                                    <b className="uppercase">{status()}</b>
                                                </Tag>
                                                {experimentResults && experimentData.end_date && (
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
                                    {experimentData.start_date ? (
                                        <EditableField
                                            multiline
                                            name="description"
                                            value={experimentData.description || ''}
                                            placeholder="Description (optional)"
                                            onSave={(value) => updateExperiment({ description: value })}
                                            maxLength={400} // Sync with Experiment model
                                            data-attr="experiment-description"
                                            compactButtons
                                        />
                                    ) : (
                                        <>
                                            {experimentData.description ||
                                                'There is no description for this experiment.'}
                                        </>
                                    )}
                                </span>
                            </Col>
                            {experimentData && !experimentData.start_date && (
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
                            {experimentData && experimentData.start_date && !experimentData.end_date && (
                                <LemonButton type="secondary" status="danger" onClick={() => endExperiment()}>
                                    Stop
                                </LemonButton>
                            )}
                            {experimentData?.end_date &&
                                dayjs().isSameOrAfter(dayjs(experimentData.end_date), 'day') &&
                                !experimentData.archived && (
                                    <LemonButton type="secondary" status="danger" onClick={() => archiveExperiment()}>
                                        <b>Archive</b>
                                    </LemonButton>
                                )}
                        </Row>
                    </Row>
                    <Row>
                        {showWarning && experimentResults && areResultsSignificant && !experimentData.end_date && (
                            <Row align="middle" className="significant-results">
                                <Col span={20} style={{ fontWeight: 500, color: '#497342' }}>
                                    <div>
                                        Experiment results are significant.{' '}
                                        {experimentData.end_date
                                            ? ''
                                            : 'You can end your experiment now or let it run until complete.'}
                                    </div>
                                </Col>
                                <Col span={4}>
                                    {experimentData.end_date ? (
                                        <CloseOutlined className="close-button" onClick={() => setShowWarning(false)} />
                                    ) : (
                                        <LemonButton type="primary" onClick={() => endExperiment()}>
                                            End experiment
                                        </LemonButton>
                                    )}
                                </Col>
                            </Row>
                        )}
                        {showWarning && experimentResults && !areResultsSignificant && !experimentData.end_date && (
                            <Row align="top" className="not-significant-results">
                                <Col span={23} style={{ fontWeight: 500, color: '#2D2D2D' }}>
                                    <strong>Your results are not statistically significant</strong>.{' '}
                                    {significanceBannerDetails}{' '}
                                    {experimentData?.end_date ? '' : "We don't recommend ending this experiment yet."}{' '}
                                    See our{' '}
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
                        {showWarning && experimentData.end_date && (
                            <Row align="top" className="feature-flag-mods">
                                <Col span={23} style={{ fontWeight: 500 }}>
                                    <strong>Your experiment is complete, but the feature flag is still enabled.</strong>{' '}
                                    We recommend removing the feature flag from your code completely, instead of relying
                                    on this distribution.{' '}
                                    <Link
                                        to={
                                            experimentData.feature_flag
                                                ? urls.featureFlag(experimentData.feature_flag)
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
                                    <Col span={experimentData?.start_date ? 12 : 24}>
                                        <ExperimentPreview
                                            experiment={experimentData}
                                            trendCount={trendCount}
                                            trendExposure={experimentData?.parameters.recommended_running_time}
                                            funnelSampleSize={experimentData?.parameters.recommended_sample_size}
                                            funnelConversionRate={conversionRate}
                                            funnelEntrants={
                                                experimentData?.start_date ? funnelResultsPersonsTotal : entrants
                                            }
                                        />
                                    </Col>
                                    {!experimentResultsLoading && !experimentResults && experimentData.start_date && (
                                        <Col span={12}>
                                            <ExperimentImplementationDetails experiment={experimentData} />
                                        </Col>
                                    )}
                                    {(experimentResults || experimentData.secondary_metrics?.length > 0) && (
                                        <Col className="secondary-progress" span={experimentData?.start_date ? 12 : 24}>
                                            {!!experimentData?.secondary_metrics.length && (
                                                <Col className="border-b">
                                                    <Row align="middle" justify="space-between" className="mb-2">
                                                        <Col className="card-secondary" span={2 * secondaryColumnSpan}>
                                                            Secondary metrics
                                                        </Col>
                                                        {experimentData?.parameters?.feature_flag_variants?.map(
                                                            (variant, idx) => (
                                                                <Col
                                                                    key={idx}
                                                                    span={secondaryColumnSpan}
                                                                    style={{
                                                                        color: getSeriesColor(
                                                                            getIndexForVariant(
                                                                                variant.key,
                                                                                experimentInsightType
                                                                            )
                                                                        ),
                                                                    }}
                                                                >
                                                                    <span className="text-sm">
                                                                        {capitalizeFirstLetter(variant.key)}
                                                                    </span>
                                                                </Col>
                                                            )
                                                        )}
                                                    </Row>

                                                    {experimentData.start_date ? (
                                                        secondaryMetricResultsLoading ? (
                                                            <Skeleton active paragraph={false} />
                                                        ) : (
                                                            <>
                                                                {experimentData.secondary_metrics.map((metric, idx) => (
                                                                    <Row
                                                                        className="border-t"
                                                                        key={idx}
                                                                        justify="space-between"
                                                                        style={{
                                                                            paddingTop: 8,
                                                                            paddingBottom: 8,
                                                                        }}
                                                                    >
                                                                        <Col span={2 * secondaryColumnSpan}>
                                                                            {capitalizeFirstLetter(metric.name)}
                                                                        </Col>
                                                                        {experimentData?.parameters?.feature_flag_variants?.map(
                                                                            (variant, index) => (
                                                                                <Col
                                                                                    key={index}
                                                                                    span={secondaryColumnSpan}
                                                                                >
                                                                                    {secondaryMetricResults?.[idx][
                                                                                        variant.key
                                                                                    ] ? (
                                                                                        metric.filters.insight ===
                                                                                        InsightType.FUNNELS ? (
                                                                                            <>
                                                                                                {(
                                                                                                    secondaryMetricResults?.[
                                                                                                        idx
                                                                                                    ][variant.key] * 100
                                                                                                ).toFixed(1)}
                                                                                                %
                                                                                            </>
                                                                                        ) : (
                                                                                            <>
                                                                                                {humanFriendlyNumber(
                                                                                                    secondaryMetricResults?.[
                                                                                                        idx
                                                                                                    ][variant.key]
                                                                                                )}
                                                                                            </>
                                                                                        )
                                                                                    ) : (
                                                                                        <>--</>
                                                                                    )}
                                                                                </Col>
                                                                            )
                                                                        )}
                                                                    </Row>
                                                                ))}
                                                            </>
                                                        )
                                                    ) : (
                                                        <>
                                                            {experimentData.secondary_metrics.map((metric, idx) => (
                                                                <Row
                                                                    className="border-t"
                                                                    key={idx}
                                                                    justify="space-between"
                                                                    style={{
                                                                        paddingTop: 8,
                                                                        paddingBottom: 8,
                                                                    }}
                                                                >
                                                                    <Col span={2 * secondaryColumnSpan}>
                                                                        {capitalizeFirstLetter(metric.name)}
                                                                    </Col>
                                                                    {experimentData?.parameters?.feature_flag_variants?.map(
                                                                        (_, index) => (
                                                                            <Col key={index} span={secondaryColumnSpan}>
                                                                                --
                                                                            </Col>
                                                                        )
                                                                    )}
                                                                </Row>
                                                            ))}
                                                        </>
                                                    )}
                                                </Col>
                                            )}
                                            {experimentResults && (
                                                <Col className="mt-4">
                                                    <div className="mb-2">
                                                        <b>Experiment progress</b>
                                                    </div>
                                                    <Progress
                                                        strokeWidth={20}
                                                        showInfo={false}
                                                        percent={experimentProgressPercent}
                                                        strokeColor="var(--success)"
                                                    />
                                                    {experimentInsightType === InsightType.TRENDS &&
                                                        experimentData.start_date && (
                                                            <Row justify="space-between" className="mt-2">
                                                                {experimentData.end_date ? (
                                                                    <div>
                                                                        Ran for{' '}
                                                                        <b>
                                                                            {dayjs(experimentData.end_date).diff(
                                                                                experimentData.start_date,
                                                                                'day'
                                                                            )}
                                                                        </b>{' '}
                                                                        days
                                                                    </div>
                                                                ) : (
                                                                    <div>
                                                                        <b>
                                                                            {dayjs().diff(
                                                                                experimentData.start_date,
                                                                                'day'
                                                                            )}
                                                                        </b>{' '}
                                                                        days running
                                                                    </div>
                                                                )}
                                                                <div>
                                                                    Goal:{' '}
                                                                    <b>
                                                                        {
                                                                            experimentData?.parameters
                                                                                ?.recommended_running_time
                                                                        }
                                                                    </b>{' '}
                                                                    days
                                                                </div>
                                                            </Row>
                                                        )}
                                                    {experimentInsightType === InsightType.FUNNELS && (
                                                        <Row justify="space-between" className="mt-2">
                                                            {experimentData.end_date ? (
                                                                <div>
                                                                    Saw{' '}
                                                                    <b>
                                                                        {humanFriendlyNumber(funnelResultsPersonsTotal)}
                                                                    </b>{' '}
                                                                    participants
                                                                </div>
                                                            ) : (
                                                                <div>
                                                                    <b>
                                                                        {humanFriendlyNumber(funnelResultsPersonsTotal)}
                                                                    </b>{' '}
                                                                    participants seen
                                                                </div>
                                                            )}
                                                            <div>
                                                                Goal:{' '}
                                                                <b>
                                                                    {humanFriendlyNumber(
                                                                        experimentData.parameters
                                                                            ?.recommended_sample_size || 0
                                                                    )}
                                                                </b>{' '}
                                                                participants
                                                            </div>
                                                        </Row>
                                                    )}
                                                </Col>
                                            )}
                                        </Col>
                                    )}
                                </Row>
                            </Collapse.Panel>
                        </Collapse>
                        {!experimentData?.start_date && (
                            <div className="mt-4 w-full">
                                <ExperimentImplementationDetails experiment={experimentData} />
                            </div>
                        )}
                    </Row>
                    <div className="experiment-result">
                        {experimentResults ? (
                            <>
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
                            </>
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
                                            display: experimentData.filters.display,
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
                            experimentData.start_date && (
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
            )
            }
        </>
    )
}

// function ExperimentParticipationSelection(): JSX.Element {
//     const { experiment, experimentId, aggregationLabel, groupTypes, taxonomicGroupTypesForSelection, flagAvailabilityWarning, experimentInsightType } = useValues(experimentLogic)
//     const { setExperiment } = useActions(experimentLogic)

//     return (
//         <Group name={["filters"]}>
//             <Row className="person-selection">
//                 <div className="mb-2">
//                     <strong>Select participants</strong>
//                 </div>
//                 <Col>
//                     <div className="text-muted">
//                         Select the entities who will participate in this experiment. If no
//                         filters are set, 100% of participants will be targeted.
//                     </div>
//                     <div className="mt-4 mb-2">
//                         <strong>Participant type</strong>
//                     </div>
//                     <Select
//                         value={
//                             experiment?.filters?.aggregation_group_type_index !=
//                                 undefined
//                                 ? experiment.filters.aggregation_group_type_index
//                                 : -1
//                         }
//                         onChange={(value) => {
//                             const groupTypeIndex = value !== -1 ? value : undefined
//                             if (
//                                 groupTypeIndex !=
//                                 experiment?.filters?.aggregation_group_type_index
//                             ) {
//                                 setFilters({
//                                     properties: [],
//                                     aggregation_group_type_index: groupTypeIndex,
//                                 })
//                                 setExperiment({
//                                     filters: {
//                                         aggregation_group_type_index: groupTypeIndex,
//                                         // :TRICKY: We reset property filters after changing what you're aggregating by.
//                                         properties: [],
//                                     },
//                                 })
//                             }
//                         }}
//                         data-attr="participant-aggregation-filter"
//                         dropdownMatchSelectWidth={false}
//                     >
//                         <Select.Option key={-1} value={-1}>
//                             Persons
//                         </Select.Option>
//                         {groupTypes.map((groupType) => (
//                             <Select.Option
//                                 key={groupType.group_type_index}
//                                 value={groupType.group_type_index}
//                             >
//                                 {capitalizeFirstLetter(
//                                     aggregationLabel(groupType.group_type_index).plural
//                                 )}
//                             </Select.Option>
//                         ))}
//                     </Select>
//                     <div className="mt-4 mb-2">
//                         <strong>Filters</strong>
//                     </div>
//                     <div className="mb-4">
//                         <PropertyFilters
//                             pageKey={'experiment-participants-property'}
//                             propertyFilters={
//                                 experimentInsightType === InsightType.FUNNELS
//                                     ? convertPropertyGroupToProperties(
//                                         funnelsFilters.properties
//                                     )
//                                     : convertPropertyGroupToProperties(
//                                         trendsFilters.properties
//                                     )
//                             }
//                             onChange={(anyProperties) => {
//                                 setExperiment({
//                                     filters: {
//                                         properties: anyProperties as PropertyFilter[],
//                                     },
//                                 })
//                                 setFilters({
//                                     properties: anyProperties.filter(isValidPropertyFilter),
//                                 })
//                             }}
//                             taxonomicGroupTypes={taxonomicGroupTypesForSelection}
//                         />
//                     </div>
//                     {flagAvailabilityWarning && (
//                         <AlertMessage type="info" className="mt-3 mb-3">
//                             These properties aren't immediately available on first page load
//                             for unidentified persons. This experiment requires that at least
//                             one event is sent prior to becoming available to your product or
//                             website.{' '}
//                             <a
//                                 href="https://posthog.com/docs/integrate/client/js#bootstrapping-flags"
//                                 target="_blank"
//                             >
//                                 {' '}
//                                 Learn more about how to make feature flags available
//                                 instantly.
//                             </a>
//                         </AlertMessage>
//                     )}
//                     <div className="mt-4 mb-2">
//                         <strong>Advanced Options</strong>
//                     </div>
//                     <div className="mb-4">
//                         For more advanced options like changing the rollout percentage and
//                         persisting feature flags, you can{' '}
//                         {experimentId === 'new' ? (
//                             'change settings on the feature flag after creation.'
//                         ) : (
//                             <Link
//                                 to={
//                                     experiment.feature_flag
//                                         ? urls.featureFlag(experiment.feature_flag)
//                                         : undefined
//                                 }
//                             >
//                                 change settings on the feature flag.
//                             </Link>
//                         )}
//                     </div>
//                 </Col>
//             </Row>
//         </Group>
//     )
// }

// function ExperimentGoalMetrics(): JSX.Element {
//     const { experimentInsightType, flagImplementationWarning, experimentInsightId } = useValues(experimentLogic)
//     const { setExperimentInsightType, setExperiment } = useActions(experimentLogic)
//     const { insightProps } = useValues(
//         insightLogic({
//             dashboardItemId: experimentInsightId,
//         })
//     )
//     const {
//         isStepsEmpty,
//         filterSteps,
//         filters: funnelsFilters,
//         results,
//         conversionMetrics,
//     } = useValues(funnelLogic(insightProps))
//     const { filters: trendsFilters, results: trendResults } = useValues(trendsLogic(insightProps))
//     return (
//         <Row className="metrics-selection">
//             <Col span={12}>
//                 <div className="mb-2" data-attr="experiment-goal-type">
//                     <b>Goal type</b>
//                     <div className="text-muted">
//                         {experimentInsightType === InsightType.TRENDS
//                             ? 'Track counts of a specific event or action'
//                             : 'Track how many persons complete a sequence of actions and or events'}
//                     </div>
//                 </div>
//                 <Select
//                     style={{ display: 'flex' }}
//                     value={experimentInsightType}
//                     onChange={setExperimentInsightType}
//                     suffixIcon={<CaretDownOutlined />}
//                     dropdownMatchSelectWidth={false}
//                 >
//                     <Select.Option value={InsightType.TRENDS}>
//                         <Col>
//                             <span>
//                                 <b>Trend</b>
//                             </span>
//                         </Col>
//                     </Select.Option>
//                     <Select.Option value={InsightType.FUNNELS}>
//                         <Col>
//                             <span>
//                                 <b>Conversion funnel</b>
//                             </span>
//                         </Col>
//                     </Select.Option>
//                 </Select>
//                 <div className="my-4">
//                     <b>Experiment goal</b>
//                     {experimentInsightType === InsightType.TRENDS && (
//                         <div className="text-muted">
//                             Trend-based experiments can have at most one graph series. This
//                             metric is used to track the progress of your experiment.
//                         </div>
//                     )}
//                 </div>
//                 {flagImplementationWarning && (
//                     <AlertMessage type="info" className="mt-3 mb-3">
//                         We can't detect any feature flag information for this target metric.
//                         Ensure that you're using the latest PostHog client libraries, and
//                         make sure you manually send feature flag information for server-side
//                         libraries if necessary.{' '}
//                         <a
//                             href="https://posthog.com/docs/integrate/server/python#capture"
//                             target="_blank"
//                         >
//                             {' '}
//                             Read the docs for how to do this for server-side libraries.
//                         </a>
//                     </AlertMessage>
//                 )}
//                 {experimentInsightType === InsightType.FUNNELS && (
//                     <ActionFilter
//                         bordered
//                         filters={funnelsFilters}
//                         setFilters={(payload) => {
//                             setExperiment({ filters: payload })
//                             setFilters(payload)
//                         }}
//                         typeKey={`experiment-funnel-goal`}
//                         mathAvailability={MathAvailability.None}
//                         hideDeleteBtn={filterSteps.length === 1}
//                         buttonCopy="Add funnel step"
//                         showSeriesIndicator={!isStepsEmpty}
//                         seriesIndicatorType="numeric"
//                         sortable
//                         showNestedArrow={true}
//                         propertiesTaxonomicGroupTypes={[
//                             TaxonomicFilterGroupType.EventProperties,
//                             TaxonomicFilterGroupType.PersonProperties,
//                             TaxonomicFilterGroupType.EventFeatureFlags,
//                             TaxonomicFilterGroupType.Cohorts,
//                             TaxonomicFilterGroupType.Elements,
//                         ]}
//                     />
//                 )}
//                 {experimentInsightType === InsightType.TRENDS && (
//                     <ActionFilter
//                         bordered
//                         filters={trendsFilters}
//                         setFilters={(payload: Partial<FilterType>) => {
//                             setExperiment({ filters: payload })
//                             setFilters(payload)
//                         }}
//                         typeKey={`experiment-trends`}
//                         buttonCopy="Add graph series"
//                         showSeriesIndicator
//                         entitiesLimit={1}
//                         hideDeleteBtn
//                         propertiesTaxonomicGroupTypes={[
//                             TaxonomicFilterGroupType.EventProperties,
//                             TaxonomicFilterGroupType.PersonProperties,
//                             TaxonomicFilterGroupType.EventFeatureFlags,
//                             TaxonomicFilterGroupType.Cohorts,
//                             TaxonomicFilterGroupType.Elements,
//                         ]}
//                     />
//                 )}
//             </Col>
//         </Row>
//     )
// } 
