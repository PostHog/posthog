import SaveOutlined from '@ant-design/icons/lib/icons/SaveOutlined'
import {
    Button,
    Card,
    Col,
    Collapse,
    Form,
    Input,
    InputNumber,
    Progress,
    Row,
    Select,
    Slider,
    Tag,
    Tooltip,
} from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React, { useState } from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import {
    ChartDisplayType,
    ActionFilter as ActionFilterType,
    FilterType,
    FunnelStep,
    FunnelVizType,
    InsightType,
    MultivariateFlagVariant,
    PropertyFilter,
} from '~/types'
import './Experiment.scss'
import { experimentLogic } from './experimentLogic'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { IconJavascript, IconOpenInNew } from 'lib/components/icons'
import { CaretDownOutlined, PlusOutlined, DeleteOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { dayjs } from 'lib/dayjs'
import PropertyFilterButton from 'lib/components/PropertyFilters/components/PropertyFilterButton'
import { FunnelLayout } from 'lib/constants'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { capitalizeFirstLetter } from 'lib/utils'
import { getSeriesColor } from 'scenes/funnels/funnelUtils'
import { getChartColors } from 'lib/colors'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'

export const scene: SceneExport = {
    component: Experiment,
    logic: experimentLogic,
}

export function Experiment(): JSX.Element {
    const {
        newExperimentData,
        experimentData,
        experimentInsightId,
        minimumSampleSizePerVariant,
        recommendedExposureForCountData,
        variants,
        expectedRunningTime,
        experimentResults,
        countDataForVariant,
        editingExistingExperiment,
        experimentInsightType,
        experimentResultsLoading,
        areResultsSignificant,
        experimentId,
        conversionRateForVariant,
    } = useValues(experimentLogic)
    const {
        setNewExperimentData,
        createExperiment,
        launchExperiment,
        setFilters,
        setEditExperiment,
        endExperiment,
        addExperimentGroup,
        updateExperimentGroup,
        removeExperimentGroup,
        setExperimentInsightType,
        archiveExperiment,
    } = useActions(experimentLogic)

    const [form] = Form.useForm()

    const [showWarning, setShowWarning] = useState(true)

    const { insightProps } = useValues(
        insightLogic({
            dashboardItemId: experimentInsightId,
            syncWithUrl: false,
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
    const runningTime = expectedRunningTime(entrants, sampleSize)
    const exposure = recommendedExposureForCountData(trendCount)

    // Parameters for experiment results
    // don't use creation variables in results
    const funnelResultsPersonsTotal =
        experimentInsightType === InsightType.FUNNELS &&
        experimentResults?.insight &&
        (experimentResults.insight as FunnelStep[][]).reduce(
            (sum: number, variantResult: FunnelStep[]) => variantResult[0].count + sum,
            0
        )
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

    return (
        <>
            {experimentId === 'new' || editingExistingExperiment ? (
                <>
                    <Row
                        align="middle"
                        justify="space-between"
                        style={{ borderBottom: '1px solid var(--border)', marginBottom: '1rem', paddingBottom: 8 }}
                    >
                        <PageHeader title={'New Experiment'} />
                    </Row>
                    <Form
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
                        scrollToFirstError
                    >
                        <div>
                            <BindLogic logic={insightLogic} props={insightProps}>
                                <Row>
                                    <Col span={12} style={{ paddingRight: 24 }}>
                                        <Row className="full-width">
                                            <Form.Item
                                                label="Name"
                                                name="name"
                                                rules={[{ required: true, message: 'You have to enter a name.' }]}
                                            >
                                                <Input data-attr="experiment-name" className="ph-ignore-input" />
                                            </Form.Item>
                                            <Form.Item
                                                style={{ paddingLeft: 16 }}
                                                label={
                                                    <div>
                                                        Feature flag key{' '}
                                                        <Tooltip title="This feature flag key should be unique from any existing ones and will be associated with this experiment.">
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
                                            <Input.TextArea
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
                                                    Experiments may have at most 3 test groups.
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
                                                                validateTrigger={['onChange', 'onBlur']}
                                                            >
                                                                <Row className="feature-flag-variant">
                                                                    <Form.Item
                                                                        name="key"
                                                                        rules={[
                                                                            {
                                                                                required: true,
                                                                                message: 'Key should not be empty.',
                                                                            },
                                                                            {
                                                                                pattern: /^([A-z]|[a-z]|[0-9]|-|_)+$/,
                                                                                message:
                                                                                    'Only letters, numbers, hyphens (-) & underscores (_) are allowed.',
                                                                            },
                                                                        ]}
                                                                    >
                                                                        <Input
                                                                            disabled={idx === 0}
                                                                            data-attr="feature-flag-variant-key"
                                                                            data-key-index={idx.toString()}
                                                                            className="ph-ignore-input"
                                                                            style={{ minWidth: 300 }}
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
                                                                                <Button
                                                                                    type="link"
                                                                                    icon={<DeleteOutlined />}
                                                                                    onClick={() =>
                                                                                        removeExperimentGroup(idx)
                                                                                    }
                                                                                    style={{
                                                                                        color: 'var(--danger)',
                                                                                        float: 'right',
                                                                                    }}
                                                                                />
                                                                            </Tooltip>
                                                                        )}
                                                                    </div>
                                                                </Row>
                                                            </Form>
                                                        )
                                                    )}

                                                    {newExperimentData.parameters.feature_flag_variants.length < 4 && (
                                                        <div>
                                                            <Button
                                                                style={{
                                                                    color: 'var(--primary)',
                                                                    border: 'none',
                                                                    boxShadow: 'none',
                                                                    marginTop: '1rem',
                                                                    paddingLeft: 0,
                                                                }}
                                                                icon={<PlusOutlined />}
                                                                onClick={() => addExperimentGroup()}
                                                            >
                                                                Add test variant
                                                            </Button>
                                                        </div>
                                                    )}
                                                </Col>
                                            </Col>
                                        )}
                                        <Form.Item label="Select participants" name="person-selection">
                                            <Col>
                                                <div className="text-muted">
                                                    Select the entities who will participate in this experiment. If no
                                                    filters are set, 100% of participants will be targeted.
                                                </div>
                                                <div style={{ flex: 3, marginRight: 5 }}>
                                                    <PropertyFilters
                                                        endpoint="person"
                                                        pageKey={'EditFunnel-property'}
                                                        propertyFilters={
                                                            experimentInsightType === InsightType.FUNNELS
                                                                ? funnelsFilters.properties
                                                                : trendsFilters.properties
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
                                                        style={{ margin: '1rem 0 0' }}
                                                        taxonomicGroupTypes={[
                                                            TaxonomicFilterGroupType.PersonProperties,
                                                            TaxonomicFilterGroupType.CohortsWithAllUsers,
                                                        ]}
                                                        popoverPlacement="top"
                                                        taxonomicPopoverPlacement="auto"
                                                    />
                                                </div>
                                            </Col>
                                        </Form.Item>
                                        <Row className="metrics-selection">
                                            <Col style={{ paddingRight: 8 }}>
                                                <div className="mb-05">
                                                    <b>Goal type</b>
                                                    <div className="text-muted">
                                                        {experimentInsightType === InsightType.TRENDS
                                                            ? 'Track how many participants complete a specific event or action'
                                                            : 'Track how many persons complete a sequence of actions and or events'}
                                                    </div>
                                                </div>
                                                <Select
                                                    style={{ display: 'flex' }}
                                                    defaultValue={experimentInsightType}
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
                                                <div className="mb mt">
                                                    <b>Experiment goal</b>
                                                    {experimentInsightType === InsightType.TRENDS && (
                                                        <div className="text-muted">
                                                            Trend-based experiments can have at most one graph series.
                                                            This metric is used to track the progress of your
                                                            experiment.
                                                        </div>
                                                    )}
                                                </div>
                                                <Row>
                                                    <Card
                                                        className="action-filters-bordered"
                                                        style={{ width: '100%', marginRight: 8 }}
                                                        bodyStyle={{ padding: 0 }}
                                                    >
                                                        {experimentInsightType === InsightType.FUNNELS && (
                                                            <ActionFilter
                                                                filters={funnelsFilters}
                                                                setFilters={(payload) => {
                                                                    setNewExperimentData({ filters: payload })
                                                                    setFilters(payload)
                                                                }}
                                                                typeKey={`EditFunnel-action`}
                                                                hideMathSelector={true}
                                                                hideDeleteBtn={filterSteps.length === 1}
                                                                buttonCopy="Add funnel step"
                                                                showSeriesIndicator={!isStepsEmpty}
                                                                seriesIndicatorType="numeric"
                                                                fullWidth
                                                                sortable
                                                                showNestedArrow={true}
                                                                propertiesTaxonomicGroupTypes={[
                                                                    TaxonomicFilterGroupType.EventProperties,
                                                                    TaxonomicFilterGroupType.PersonProperties,
                                                                    TaxonomicFilterGroupType.Cohorts,
                                                                    TaxonomicFilterGroupType.Elements,
                                                                ]}
                                                                rowClassName="action-filters-bordered"
                                                            />
                                                        )}
                                                        {experimentInsightType === InsightType.TRENDS && (
                                                            <ActionFilter
                                                                horizontalUI
                                                                filters={trendsFilters}
                                                                setFilters={(payload: Partial<FilterType>) => {
                                                                    setNewExperimentData({ filters: payload })
                                                                    setFilters(payload)
                                                                }}
                                                                typeKey={`experiment-trends`}
                                                                buttonCopy="Add graph series"
                                                                showSeriesIndicator
                                                                singleFilter={true}
                                                                hideMathSelector={true}
                                                                propertiesTaxonomicGroupTypes={[
                                                                    TaxonomicFilterGroupType.EventProperties,
                                                                    TaxonomicFilterGroupType.PersonProperties,
                                                                    TaxonomicFilterGroupType.Cohorts,
                                                                    TaxonomicFilterGroupType.Elements,
                                                                ]}
                                                                customRowPrefix={
                                                                    trendsFilters.insight === InsightType.LIFECYCLE ? (
                                                                        <>
                                                                            Showing <b>Unique users</b> who did
                                                                        </>
                                                                    ) : undefined
                                                                }
                                                            />
                                                        )}
                                                    </Card>
                                                </Row>
                                            </Col>
                                        </Row>
                                    </Col>
                                    <Col span={12}>
                                        <Card className="experiment-preview">
                                            <ExperimentPreview
                                                experiment={newExperimentData}
                                                trendCount={trendCount}
                                                exposure={exposure}
                                                sampleSize={sampleSize}
                                                runningTime={runningTime}
                                                conversionRate={conversionRate}
                                            />
                                            <InsightContainer
                                                disableHeader={experimentInsightType === InsightType.TRENDS}
                                                disableTable={true}
                                            />
                                        </Card>
                                    </Col>
                                </Row>
                            </BindLogic>
                        </div>
                        <Button icon={<SaveOutlined />} className="float-right" type="primary" htmlType="submit">
                            Save
                        </Button>
                    </Form>
                </>
            ) : experimentData ? (
                <div className="view-experiment">
                    <Row className="draft-header">
                        <Row justify="space-between" align="middle" className="full-width pb">
                            <Col>
                                <Row>
                                    <PageHeader
                                        style={{ margin: 0, paddingRight: 8 }}
                                        title={`${experimentData?.name}`}
                                    />
                                    <CopyToClipboardInline
                                        explicitValue={experimentData.feature_flag_key}
                                        iconStyle={{ color: 'var(--text-muted-alt)' }}
                                    >
                                        <span className="text-muted">{experimentData.feature_flag_key}</span>
                                    </CopyToClipboardInline>
                                    <Tag
                                        style={{ alignSelf: 'center', marginLeft: '1rem' }}
                                        color={statusColors[status()]}
                                    >
                                        <b className="uppercase">{status()}</b>
                                    </Tag>
                                </Row>
                                <span className="description">
                                    {experimentData.description || 'There is no description for this experiment.'}
                                </span>
                            </Col>
                            {experimentData && !experimentData.start_date && (
                                <div>
                                    <Button className="mr-05" onClick={() => setEditExperiment(true)}>
                                        Edit
                                    </Button>
                                    <Button type="primary" onClick={() => launchExperiment()}>
                                        Launch
                                    </Button>
                                </div>
                            )}
                            {experimentData && experimentData.start_date && !experimentData.end_date && (
                                <Button className="stop-experiment" onClick={() => endExperiment()}>
                                    Stop experiment
                                </Button>
                            )}
                            {experimentData?.end_date &&
                                dayjs().isSameOrAfter(dayjs(experimentData.end_date), 'day') &&
                                !experimentData.archived && (
                                    <Button className="archive-experiment" onClick={() => archiveExperiment()}>
                                        <b>Archive experiment</b>
                                    </Button>
                                )}
                        </Row>
                    </Row>
                    <Row>
                        {showWarning && experimentResults && areResultsSignificant && (
                            <Row align="middle" className="significant-results">
                                <Col span={19} style={{ color: '#497342' }}>
                                    Your results are <b>statistically significant</b>. You can end this experiment now
                                    or let it run to completion.
                                </Col>
                                <Col span={5}>
                                    <Button style={{ color: '#497342' }} onClick={() => setShowWarning(false)}>
                                        Dismiss
                                    </Button>
                                </Col>
                            </Row>
                        )}
                        {showWarning && experimentResults && !areResultsSignificant && (
                            <Row align="middle" className="not-significant-results">
                                <Col span={19} style={{ color: '#f96132' }}>
                                    Your results are <b>not statistically significant</b>. We don't recommend ending
                                    this experiment yet.
                                </Col>
                                <Col span={5}>
                                    <Button style={{ color: '#f96132' }} onClick={() => setShowWarning(false)}>
                                        Dismiss
                                    </Button>
                                </Col>
                            </Row>
                        )}
                    </Row>
                    <Row>
                        <Collapse className="full-width" defaultActiveKey="experiment-details">
                            <Collapse.Panel header={<b>Experiment details</b>} key="experiment-details">
                                <ExperimentPreview
                                    experiment={experimentData}
                                    trendCount={trendCount}
                                    exposure={experimentData?.parameters.recommended_running_time}
                                    sampleSize={experimentData?.parameters.recommended_sample_size}
                                    runningTime={runningTime}
                                    conversionRate={conversionRate}
                                />
                                {experimentResults && (
                                    <Col span={8} className="mt ml">
                                        <div className="mb-05">
                                            <b>Experiment progress</b>
                                        </div>
                                        <Progress
                                            strokeWidth={20}
                                            showInfo={false}
                                            percent={experimentProgressPercent}
                                            strokeColor="var(--success)"
                                        />
                                        {experimentInsightType === InsightType.TRENDS && experimentData.start_date && (
                                            <Row justify="space-between" className="mt-05">
                                                <div>
                                                    <b>{dayjs().diff(experimentData.start_date, 'day')}</b> days running
                                                </div>
                                                <div>
                                                    Goal: <b>{experimentData?.parameters?.recommended_running_time}</b>{' '}
                                                    days
                                                </div>
                                            </Row>
                                        )}
                                        {experimentInsightType === InsightType.FUNNELS && (
                                            <Row justify="space-between" className="mt-05">
                                                <div>
                                                    <b>{funnelResultsPersonsTotal}</b> participants seen
                                                </div>
                                                <div>
                                                    Goal: <b>{experimentData?.parameters?.recommended_sample_size}</b>{' '}
                                                    participants
                                                </div>
                                            </Row>
                                        )}
                                    </Col>
                                )}
                            </Collapse.Panel>
                        </Collapse>
                    </Row>
                    <div className="experiment-result">
                        {experimentResults ? (
                            <>
                                <Row justify="space-around" style={{ flexFlow: 'nowrap' }}>
                                    {Object.keys(experimentResults.probability)
                                        .reverse()
                                        .map((variant, idx) => (
                                            <Col key={idx} className="pr">
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
                                                    strokeColor={
                                                        experimentInsightType === InsightType.FUNNELS
                                                            ? getSeriesColor(idx + 1)
                                                            : getChartColors('white')[idx]
                                                    }
                                                />
                                                <div>
                                                    Probability that this variant is the best:{' '}
                                                    <b>{(experimentResults.probability[variant] * 100).toFixed(1)}%</b>
                                                </div>
                                            </Col>
                                        ))}
                                </Row>
                            </>
                        ) : experimentResultsLoading ? (
                            <div className="text-center">
                                <Spinner />
                            </div>
                        ) : (
                            <span style={{ fontWeight: 500 }}>
                                There are no results for this experiment yet.{' '}
                                {!experimentData.start_date && 'Launch this experiment to start it!'}
                            </span>
                        )}
                        {experimentResults ? (
                            <BindLogic
                                logic={insightLogic}
                                props={{
                                    dashboardItemId: experimentResults.itemID,
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
                                    cachedResults: experimentResults.insight,
                                    syncWithUrl: false,
                                    doNotLoad: true,
                                }}
                            >
                                <div className="mt">
                                    <InsightContainer
                                        disableHeader={experimentInsightType === InsightType.TRENDS}
                                        disableTable={experimentInsightType === InsightType.FUNNELS}
                                    />
                                </div>
                            </BindLogic>
                        ) : (
                            <div
                                style={{
                                    display: 'flex',
                                    justifyContent: 'center',
                                    alignItems: 'center',
                                    marginTop: 16,
                                    background: '#FAFAF9',
                                    border: '1px solid var(--border)',
                                    width: '100%',
                                    minHeight: 320,
                                    fontSize: 24,
                                }}
                            >
                                {experimentResultsLoading ? (
                                    <Spinner />
                                ) : (
                                    <b>There are no results for this experiment yet.</b>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            ) : (
                <div>Loading Data...</div>
            )}
        </>
    )
}

export function CodeLanguageSelect(): JSX.Element {
    return (
        <Select defaultValue="JavaScript" suffixIcon={<CaretDownOutlined />}>
            <Select.Option value="JavaScript">
                <Row align="middle">
                    <IconJavascript style={{ marginRight: 6 }} /> JavaScript
                </Row>
            </Select.Option>
        </Select>
    )
}

interface ExperimentPreviewProps {
    experiment: Partial<any> | null
    trendCount: number
    exposure?: number
    conversionRate: number
    runningTime: number
    sampleSize?: number
}

export function ExperimentPreview({
    experiment,
    trendCount,
    exposure,
    conversionRate,
    runningTime,
    sampleSize,
}: ExperimentPreviewProps): JSX.Element {
    const { experimentInsightType, experimentId, editingExistingExperiment, minimumDetectableChange } =
        useValues(experimentLogic)
    const { setNewExperimentData } = useActions(experimentLogic)
    const [currentVariant, setCurrentVariant] = useState('control')
    const sliderMaxValue =
        experimentInsightType === InsightType.FUNNELS ? (100 - conversionRate < 50 ? 100 - conversionRate : 50) : 50

    return (
        <Row>
            <Col span={experimentId === 'new' || editingExistingExperiment ? 24 : 12}>
                <Row className="experiment-preview-row">
                    {experimentId !== 'new' ? (
                        <Col>
                            <div className="card-secondary mb-05">Preview</div>
                        </Col>
                    ) : (
                        <div>
                            <div>
                                <b>Experiment preview</b>
                            </div>
                            <div className="text-muted">
                                Here are the baseline metrics for your experiment. Adjust your minimum detectible
                                threshold to adjust for the smallest conversion value you’ll accept, and the experiment
                                duration.{' '}
                            </div>
                        </div>
                    )}
                </Row>
                {(experimentId === 'new' || editingExistingExperiment) && (
                    <Row className="mb">
                        <Col span={24}>
                            <div>
                                <b>Minimum acceptable improvement</b>
                                <Tooltip
                                    title={
                                        'Minimum acceptable improvement is a calculation that estimates the smallest significant improvement you are willing to accept.'
                                    }
                                >
                                    <InfoCircleOutlined style={{ marginLeft: 4 }} />
                                </Tooltip>
                            </div>
                            <Row className="mde-slider">
                                <Col span={8}>
                                    <Slider
                                        defaultValue={5}
                                        value={minimumDetectableChange}
                                        min={1}
                                        max={sliderMaxValue}
                                        trackStyle={{ background: 'var(--primary)' }}
                                        handleStyle={{ background: 'var(--primary)' }}
                                        onChange={(value) => {
                                            setNewExperimentData({
                                                parameters: { minimum_detectable_effect: value },
                                            })
                                        }}
                                        tipFormatter={(value) => `${value}%`}
                                    />
                                </Col>
                                <InputNumber
                                    min={1}
                                    max={sliderMaxValue}
                                    defaultValue={5}
                                    formatter={(value) => `${value}%`}
                                    style={{ margin: '0 16px' }}
                                    value={minimumDetectableChange}
                                    onChange={(value) => {
                                        setNewExperimentData({
                                            parameters: { minimum_detectable_effect: value },
                                        })
                                    }}
                                />
                            </Row>
                        </Col>
                    </Row>
                )}
                <Row className="experiment-preview-row">
                    {experimentInsightType === InsightType.TRENDS ? (
                        <>
                            {!experiment?.start_date && (
                                <>
                                    <Col span={6}>
                                        <div className="card-secondary">Baseline Count</div>
                                        <div className="l4">{trendCount}</div>
                                    </Col>
                                    <Col span={6}>
                                        <div className="card-secondary">Minimum Acceptable Count</div>
                                        <div className="l4">
                                            {trendCount + Math.ceil(trendCount * (minimumDetectableChange / 100))}
                                        </div>
                                    </Col>
                                </>
                            )}
                            <Col span={12}>
                                <div className="card-secondary">Recommended running time</div>
                                <div>
                                    <span className="l4">~{exposure}</span> days
                                </div>
                            </Col>
                        </>
                    ) : (
                        <>
                            {!experiment?.start_date && (
                                <>
                                    <Col span={12}>
                                        <div className="card-secondary">Baseline Conversion Rate</div>
                                        <div className="l4">{conversionRate.toFixed(1)}%</div>
                                    </Col>
                                    <Col span={12}>
                                        <div className="card-secondary">Minimum Acceptable Conversion Rate</div>
                                        <div className="l4">
                                            {(conversionRate + minimumDetectableChange).toFixed(1)}%
                                        </div>
                                    </Col>
                                </>
                            )}
                            <Col span={12}>
                                <div className="card-secondary">Recommended Sample Size</div>
                                <div className="pb">
                                    <span className="l4">~{sampleSize}</span> persons
                                </div>
                            </Col>
                            {!experiment?.start_date && (
                                <Col span={12}>
                                    <div className="card-secondary">Recommended running time</div>
                                    <div>
                                        <span className="l4">~{runningTime}</span> days
                                    </div>
                                </Col>
                            )}
                        </>
                    )}
                    <Row className="full-width mt">
                        <Col span={12}>
                            <div className="card-secondary">Experiment variants</div>
                            <ul className="variants-list">
                                {experiment?.parameters?.feature_flag_variants?.map(
                                    (variant: MultivariateFlagVariant, idx: number) => (
                                        <li key={idx}>{variant.key}</li>
                                    )
                                )}
                            </ul>
                        </Col>
                        <Col span={12}>
                            <div className="card-secondary">Participants</div>
                            <div>
                                {!!experiment?.filters?.properties?.length ? (
                                    <div>
                                        {experiment?.filters.properties.map((item: PropertyFilter) => {
                                            return <PropertyFilterButton key={item.key} item={item} greyBadges={true} />
                                        })}
                                    </div>
                                ) : (
                                    '100% of users'
                                )}
                            </div>
                        </Col>
                    </Row>
                    <Row>
                        {experimentId !== 'new' && (
                            <Col className="mr">
                                <div className="card-secondary mt">Start date</div>
                                {experiment?.start_date ? (
                                    <span>{dayjs(experiment?.start_date).format('D MMM YYYY')}</span>
                                ) : (
                                    <span className="description">Not started yet</span>
                                )}
                            </Col>
                        )}
                        {experiment?.end_date && (
                            <Col className="ml">
                                <div className="card-secondary mt">Completed date</div>
                                <span>{dayjs(experiment?.end_date).format('D MMM YYYY')}</span>
                            </Col>
                        )}
                    </Row>
                </Row>
                {experimentId !== 'new' && (
                    <Row className="experiment-preview-row">
                        <Col>
                            <div className="card-secondary mb-05">
                                {experimentInsightType === InsightType.FUNNELS ? 'Conversion goal' : 'Trend goal'}
                            </div>
                            {[...(experiment?.filters?.events || []), ...(experiment?.filters?.actions || [])]
                                .sort((a, b) => a.order - b.order)
                                .map((event: ActionFilterType, idx: number) => (
                                    <Col key={idx} className="mb-05">
                                        <Row style={{ marginBottom: 4 }}>
                                            <div className="preview-conversion-goal-num">
                                                {experimentInsightType === InsightType.FUNNELS
                                                    ? (event.order || 0) + 1
                                                    : idx + 1}
                                            </div>
                                            <b>
                                                <EntityFilterInfo filter={event} />
                                            </b>
                                        </Row>
                                        {event.properties?.map((prop: PropertyFilter) => (
                                            <PropertyFilterButton key={prop.key} item={prop} greyBadges={true} />
                                        ))}
                                    </Col>
                                ))}
                        </Col>
                    </Row>
                )}
            </Col>
            {experimentId !== 'new' && (
                <Col span={12} className="pl">
                    <div className="card-secondary mb">Feature flag usage and implementation</div>
                    <Row justify="space-between" className="mb-05">
                        <div>
                            <span className="mr-05">Variant group</span>
                            <Select
                                onChange={setCurrentVariant}
                                defaultValue={'control'}
                                suffixIcon={<CaretDownOutlined />}
                            >
                                {experiment?.parameters?.feature_flag_variants?.map(
                                    (variant: MultivariateFlagVariant, idx: number) => (
                                        <Select.Option key={idx} value={variant.key}>
                                            {variant.key}
                                        </Select.Option>
                                    )
                                )}
                            </Select>
                        </div>
                        <div>
                            <CodeLanguageSelect />
                        </div>
                    </Row>
                    <b>Implement your experiment in code</b>
                    <CodeSnippet language={Language.JavaScript} wrap>
                        {`if (posthog.getFeatureFlag('${experiment?.feature_flag_key ?? ''}') === '${currentVariant}') {
    // where '${currentVariant}' is the variant, run your code here
}`}
                    </CodeSnippet>
                    <b>Test that it works</b>
                    <CodeSnippet language={Language.JavaScript}>
                        {`posthog.feature_flags.override({'${experiment?.feature_flag_key}': '${currentVariant}'})`}
                    </CodeSnippet>
                    <a
                        target="_blank"
                        rel="noopener noreferrer"
                        href="https://posthog.com/docs/user-guides/feature-flags"
                    >
                        <Row align="middle">
                            Experiment implementation guide
                            <IconOpenInNew className="ml-05" />
                        </Row>
                    </a>
                </Col>
            )}
        </Row>
    )
}
