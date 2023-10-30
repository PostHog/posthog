import { Card, Col, Popconfirm, Progress, Row, Skeleton, Tag, Tooltip } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { useEffect, useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { AvailableFeature, FunnelStep, InsightType } from '~/types'
import './Experiment.scss'
import { experimentLogic, ExperimentLogicProps } from './experimentLogic'
import { IconDelete, IconPlusMini } from 'lib/lemon-ui/icons'
import { CloseOutlined } from '@ant-design/icons'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter, humanFriendlyNumber } from 'lib/utils'
import { SecondaryMetrics } from './SecondaryMetrics'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { ExperimentPreview } from './ExperimentPreview'
import { ExperimentImplementationDetails } from './ExperimentImplementationDetails'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { router } from 'kea-router'
import { LemonDivider, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'
import { NotFound } from 'lib/components/NotFound'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Form, Group } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { userLogic } from 'scenes/userLogic'
import { ExperimentsPayGate } from './ExperimentsPayGate'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { EXPERIMENT_INSIGHT_ID } from './constants'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { Query } from '~/queries/Query/Query'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { ExperimentInsightCreator } from './MetricSelector'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { ExperimentResult } from './ExperimentResult'

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
        minimumSampleSizePerVariant,
        recommendedExposureForCountData,
        variants,
        experimentResults,
        editingExistingExperiment,
        experimentInsightType,
        experimentResultsLoading,
        experimentLoading,
        areResultsSignificant,
        significanceBannerDetails,
        isExperimentRunning,
        flagImplementationWarning,
        props,
        aggregationLabel,
        showGroupsOptions,
        groupTypes,
        experimentMissing,
    } = useValues(experimentLogic)
    const {
        launchExperiment,
        setEditExperiment,
        endExperiment,
        addExperimentGroup,
        updateExperiment,
        removeExperimentGroup,
        setNewExperimentInsight,
        archiveExperiment,
        resetRunningExperiment,
        loadExperiment,
        loadExperimentResults,
        setExposureAndSampleSize,
        updateExperimentSecondaryMetrics,
        setExperiment,
    } = useActions(experimentLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const [showWarning, setShowWarning] = useState(true)

    // insightLogic
    const logic = insightLogic({ dashboardItemId: EXPERIMENT_INSIGHT_ID })
    const { insightProps } = useValues(logic)

    // insightDataLogic
    const { query } = useValues(insightDataLogic(insightProps))

    const { conversionMetrics, results } = useValues(funnelDataLogic(insightProps))
    const { results: trendResults } = useValues(trendsDataLogic(insightProps))

    // Parameters for creating experiment
    const conversionRate = conversionMetrics.totalRate * 100
    const sampleSizePerVariant = minimumSampleSizePerVariant(conversionRate)
    const sampleSize = sampleSizePerVariant * variants.length
    const trendCount = trendResults[0]?.count
    const entrants = results?.[0]?.count
    const exposure = recommendedExposureForCountData(trendCount)

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

    const maxVariants = 10

    const variantLabelColors = [
        { background: '#35416b', color: '#fff' },
        { background: '#C278CE66', color: '#35416B' },
        { background: '#FFE6AE', color: '#35416B' },
        { background: '#8DA9E74D', color: '#35416B' },
    ]

    if (!hasAvailableFeature(AvailableFeature.EXPERIMENTATION)) {
        return (
            <>
                <PageHeader title="Experiments" />
                <ExperimentsPayGate />
            </>
        )
    }

    if (experimentLoading) {
        return <Skeleton active />
    }

    if (experimentMissing) {
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
                                        {editingExistingExperiment ? 'Save' : 'Save as draft'}
                                    </LemonButton>
                                </div>
                            }
                        />
                        <LemonDivider />

                        <BindLogic logic={insightLogic} props={insightProps}>
                            <>
                                {/* eslint-disable-next-line react/forbid-dom-props */}
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
                                                may have at most 9 test groups. Variant names can only contain letters,
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
                                                                // eslint-disable-next-line react/forbid-dom-props
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
                                        <div>
                                            <strong>Select participants</strong>
                                        </div>
                                        <div className="text-muted mb-4">
                                            Experiments use feature flags to target users. By default, 100% of
                                            participants will be targeted. For any advanced options like changing the
                                            rollout percentage, and targeting by groups, you can{' '}
                                            {experimentId === 'new' ? (
                                                'change settings on the feature flag after saving this experiment.'
                                            ) : (
                                                <Link
                                                    to={
                                                        experiment.feature_flag
                                                            ? urls.featureFlag(experiment.feature_flag.id)
                                                            : undefined
                                                    }
                                                >
                                                    change settings on the feature flag.
                                                </Link>
                                            )}
                                        </div>
                                        {experimentId === 'new' && showGroupsOptions && (
                                            <>
                                                <div className="mt-4">
                                                    <strong>Default participant type</strong>
                                                </div>
                                                <div className="text-muted mb-4">
                                                    This sets default aggregation type for all metrics and feature
                                                    flags. You can change this at any time by updating the metric or
                                                    feature flag.
                                                </div>
                                                <LemonSelect
                                                    value={
                                                        experiment.parameters.aggregation_group_type_index != undefined
                                                            ? experiment.parameters.aggregation_group_type_index
                                                            : -1
                                                    }
                                                    data-attr="participant-aggregation-filter"
                                                    dropdownMatchSelectWidth={false}
                                                    onChange={(rawGroupTypeIndex) => {
                                                        const groupTypeIndex =
                                                            rawGroupTypeIndex !== -1 ? rawGroupTypeIndex : undefined

                                                        setExperiment({
                                                            parameters: {
                                                                ...experiment.parameters,
                                                                aggregation_group_type_index:
                                                                    groupTypeIndex ?? undefined,
                                                            },
                                                        })
                                                        setNewExperimentInsight()
                                                    }}
                                                    options={[
                                                        { value: -1, label: 'Persons' },
                                                        ...Array.from(groupTypes.values()).map((groupType) => ({
                                                            value: groupType.group_type_index,
                                                            label: capitalizeFirstLetter(
                                                                aggregationLabel(groupType.group_type_index).plural
                                                            ),
                                                        })),
                                                    ]}
                                                />
                                            </>
                                        )}
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
                                                    setNewExperimentInsight({
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
                                            <LemonBanner type="info" className="mt-3 mb-3">
                                                We can't detect any feature flag information for this target metric.
                                                Ensure that you're using the latest PostHog client libraries, and make
                                                sure you manually send feature flag information for server-side
                                                libraries if necessary.{' '}
                                                <Link
                                                    to="https://posthog.com/docs/integrate/server/python#capture"
                                                    target="_blank"
                                                >
                                                    {' '}
                                                    Read the docs for how to do this for server-side libraries.
                                                </Link>
                                            </LemonBanner>
                                        )}

                                        <ExperimentInsightCreator insightProps={insightProps} />
                                    </Col>
                                    <Col span={12} className="pl-4">
                                        <div className="card-secondary mb-4" data-attr="experiment-preview">
                                            Goal preview
                                        </div>
                                        <BindLogic logic={insightLogic} props={insightProps}>
                                            <Query query={query} context={{ insightProps }} readOnly />
                                        </BindLogic>
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
                                                <div className="text-muted mt-1">
                                                    Use secondary metrics to monitor metrics related to your experiment
                                                    goal. You can add up to three secondary metrics.{' '}
                                                </div>
                                                <SecondaryMetrics
                                                    onMetricsChange={onChange}
                                                    initialMetrics={value}
                                                    experimentId={experiment.id}
                                                    defaultAggregationType={
                                                        experiment.parameters?.aggregation_group_type_index
                                                    }
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
                                {editingExistingExperiment ? 'Save' : 'Save as draft'}
                            </LemonButton>
                        </div>
                    </Form>
                </>
            ) : experiment ? (
                <div className="view-experiment">
                    <Row className="draft-header">
                        <Row justify="space-between" align="middle" className="w-full" wrap={false}>
                            <Col>
                                <PageHeader
                                    style={{ paddingRight: 8 }}
                                    title={`${experiment?.name}`}
                                    buttons={
                                        <>
                                            <CopyToClipboardInline
                                                explicitValue={experiment.feature_flag?.key}
                                                iconStyle={{ color: 'var(--muted-alt)' }}
                                            >
                                                <span className="text-muted">{experiment.feature_flag?.key}</span>
                                            </CopyToClipboardInline>
                                            <StatusTag />
                                            <ResultsTag />
                                        </>
                                    }
                                />
                            </Col>
                            <Col className="page-title-row">
                                {experiment && !isExperimentRunning && (
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
                                {experiment && isExperimentRunning && (
                                    <div className="flex flex-row gap-2">
                                        <>
                                            <More
                                                overlay={
                                                    <>
                                                        <LemonButton
                                                            status="stealth"
                                                            onClick={() => loadExperimentResults(true)}
                                                            fullWidth
                                                            data-attr="refresh-experiment"
                                                        >
                                                            Refresh experiment results
                                                        </LemonButton>
                                                    </>
                                                }
                                            />
                                            <LemonDivider vertical />
                                        </>
                                        <Popconfirm
                                            placement="bottomLeft"
                                            title={
                                                <div>
                                                    Reset this experiment and go back to draft mode?
                                                    <div className="text-sm text-muted">
                                                        All collected data so far will be discarded.
                                                    </div>
                                                    {experiment.archived && (
                                                        <div className="text-sm text-muted">
                                                            Resetting will also unarchive the experiment.
                                                        </div>
                                                    )}
                                                </div>
                                            }
                                            onConfirm={() => resetRunningExperiment()}
                                        >
                                            <LemonButton type="secondary" status="primary">
                                                Reset
                                            </LemonButton>
                                        </Popconfirm>
                                        {!experiment.end_date && (
                                            <LemonButton
                                                type="secondary"
                                                status="danger"
                                                onClick={() => endExperiment()}
                                            >
                                                Stop
                                            </LemonButton>
                                        )}
                                        {experiment?.end_date &&
                                            dayjs().isSameOrAfter(dayjs(experiment.end_date), 'day') &&
                                            !experiment.archived && (
                                                <LemonButton
                                                    type="secondary"
                                                    status="danger"
                                                    onClick={() => archiveExperiment()}
                                                >
                                                    <b>Archive</b>
                                                </LemonButton>
                                            )}
                                    </div>
                                )}
                            </Col>
                        </Row>
                        <Row className="w-full pb-4">
                            <span className="exp-description">
                                {isExperimentRunning ? (
                                    <EditableField
                                        multiline
                                        markdown
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
                                <Col span={23} style={{ fontWeight: 500, color: 'var(--bg-charcoal)' }}>
                                    <strong>Your results are not statistically significant</strong>.{' '}
                                    {significanceBannerDetails}{' '}
                                    {experiment?.end_date ? '' : "We don't recommend ending this experiment yet."} See
                                    our{' '}
                                    <Link to="https://posthog.com/docs/user-guides/experimentation#funnel-experiment-calculations">
                                        {' '}
                                        experimentation guide{' '}
                                    </Link>
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
                                                ? urls.featureFlag(experiment.feature_flag.id)
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
                        <LemonCollapse
                            className="w-full"
                            defaultActiveKey="experiment-details"
                            panels={[
                                {
                                    key: 'experiment-details',
                                    header: 'Experiment details',
                                    content: (
                                        <Row>
                                            <Col span={isExperimentRunning ? 12 : 24}>
                                                <ExperimentPreview
                                                    experimentId={experiment.id}
                                                    trendCount={trendCount}
                                                    trendExposure={experiment?.parameters.recommended_running_time}
                                                    funnelSampleSize={experiment?.parameters.recommended_sample_size}
                                                    funnelConversionRate={conversionRate}
                                                    funnelEntrants={
                                                        isExperimentRunning ? funnelResultsPersonsTotal : entrants
                                                    }
                                                />
                                            </Col>
                                            {!experimentResultsLoading && !experimentResults && isExperimentRunning && (
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
                                                    {experimentInsightType === InsightType.TRENDS &&
                                                        experiment.start_date && (
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
                                                                        <b>
                                                                            {dayjs().diff(experiment.start_date, 'day')}
                                                                        </b>{' '}
                                                                        days running
                                                                    </div>
                                                                )}
                                                                <div>
                                                                    Goal:{' '}
                                                                    <b>
                                                                        {experiment?.parameters
                                                                            ?.recommended_running_time ?? 'Unknown'}
                                                                    </b>{' '}
                                                                    days
                                                                </div>
                                                            </Row>
                                                        )}
                                                    {experimentInsightType === InsightType.FUNNELS && (
                                                        <Row justify="space-between" className="mt-2">
                                                            {experiment.end_date ? (
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
                                                                        experiment?.parameters
                                                                            ?.recommended_sample_size || 0
                                                                    )}
                                                                </b>{' '}
                                                                participants
                                                            </div>
                                                        </Row>
                                                    )}
                                                </Col>
                                            )}
                                            <Col>
                                                <SecondaryMetrics
                                                    experimentId={experiment.id}
                                                    onMetricsChange={(metrics) =>
                                                        updateExperimentSecondaryMetrics(metrics)
                                                    }
                                                    initialMetrics={experiment.secondary_metrics}
                                                    defaultAggregationType={
                                                        experiment.parameters?.aggregation_group_type_index
                                                    }
                                                />
                                            </Col>
                                        </Row>
                                    ),
                                },
                            ]}
                        />
                        {!experiment?.start_date && (
                            <div className="mt-4 w-full">
                                <ExperimentImplementationDetails experiment={experiment} />
                            </div>
                        )}
                    </Row>
                    <ExperimentResult />
                </div>
            ) : (
                <Skeleton active />
            )}
        </>
    )
}

export function StatusTag(): JSX.Element {
    const { experiment, isExperimentRunning } = useValues(experimentLogic)
    const statusColors = { running: 'green', draft: 'default', complete: 'purple' }
    const status = (): string => {
        if (!isExperimentRunning) {
            return 'draft'
        } else if (!experiment?.end_date) {
            return 'running'
        }
        return 'complete'
    }

    return (
        <Tag style={{ alignSelf: 'center' }} color={statusColors[status()]}>
            <b className="uppercase">{status()}</b>
        </Tag>
    )
}

export function ResultsTag(): JSX.Element {
    const { experiment, experimentResults, areResultsSignificant } = useValues(experimentLogic)
    if (experimentResults && experiment.end_date) {
        return (
            <Tag style={{ alignSelf: 'center' }} color={areResultsSignificant ? 'green' : 'geekblue'}>
                <b className="uppercase">{areResultsSignificant ? 'Significant Results' : 'Results not significant'}</b>
            </Tag>
        )
    }

    return <></>
}
