import SaveOutlined from '@ant-design/icons/lib/icons/SaveOutlined'
import { Alert, Button, Card, Col, Form, Input, InputNumber, Row, Select, Slider, Tag, Tooltip } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { FunnelVizType, MultivariateFlagVariant, PropertyFilter } from '~/types'
import './Experiment.scss'
import { experimentLogic } from './experimentLogic'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { JSSnippet } from 'scenes/feature-flags/FeatureFlagSnippets'
import { IconJavascript, IconOpenInNew } from 'lib/components/icons'
import { InfoCircleOutlined, CaretDownOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { dayjs } from 'lib/dayjs'
import { FunnelLayout } from 'lib/constants'

export const scene: SceneExport = {
    component: Experiment,
    logic: experimentLogic,
}

export function Experiment(): JSX.Element {
    const {
        newExperimentData,
        experimentId,
        experimentData,
        experimentFunnelId,
        minimumDetectableChange,
        recommendedSampleSize,
        expectedRunningTime,
        experimentResults,
        conversionRateForVariant,
        editingExistingExperiment,
    } = useValues(experimentLogic)
    const {
        setNewExperimentData,
        createExperiment,
        launchExperiment,
        setFilters,
        editExperiment,
        endExperiment,
        addExperimentGroup,
        updateExperimentGroup,
        removeExperimentGroup,
    } = useActions(experimentLogic)

    const [form] = Form.useForm()

    const { insightProps } = useValues(
        insightLogic({
            dashboardItemId: experimentFunnelId,
            syncWithUrl: false,
        })
    )
    const { isStepsEmpty, filterSteps, filters, results, conversionMetrics } = useValues(funnelLogic(insightProps))

    const conversionRate = conversionMetrics.totalRate * 100
    const entrants = results?.[0]?.count
    const sampleSize = recommendedSampleSize(conversionRate)
    const runningTime = expectedRunningTime(entrants, sampleSize)
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
                        onFinish={() => createExperiment(true, runningTime, sampleSize)}
                        scrollToFirstError
                    >
                        <div>
                            <Row>
                                <Col span={12} style={{ paddingRight: 24 }}>
                                    <Form.Item
                                        label="Name"
                                        name="name"
                                        rules={[{ required: true, message: 'You have to enter a name.' }]}
                                    >
                                        <Input data-attr="experiment-name" className="ph-ignore-input" />
                                    </Form.Item>
                                    <Form.Item
                                        label="Feature flag key"
                                        name="feature_flag_key"
                                        rules={[
                                            {
                                                required: true,
                                                message: 'You have to enter a feature flag key name.',
                                            },
                                        ]}
                                        help={
                                            <span className="text-small text-muted">
                                                Enter a new and unique name for the feature flag key to be associated
                                                with this experiment.
                                            </span>
                                        }
                                    >
                                        <Input
                                            data-attr="experiment-feature-flag-key"
                                            placeholder="examples: new-landing-page-experiment, betaFeatureExperiment, ab_test_1_experiment"
                                        />
                                    </Form.Item>
                                    <Form.Item label="Description" name="description">
                                        <Input.TextArea
                                            data-attr="experiment-description"
                                            className="ph-ignore-input"
                                            placeholder="Adding a helpful description can ensure others know what this experiment is about."
                                        />
                                    </Form.Item>
                                </Col>
                                <Col span={12}>
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
                                                    propertyFilters={filters.properties || []}
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
                                    {newExperimentData?.parameters?.feature_flag_variants && (
                                        <Col>
                                            <label>
                                                <b>Experiment groups</b>
                                            </label>
                                            <div className="text-muted">
                                                Participants are divided into experiment groups. All experiments must
                                                consist of a control group and at least one test group.
                                            </div>
                                            <Col>
                                                {newExperimentData.parameters.feature_flag_variants.map(
                                                    (variant: MultivariateFlagVariant, idx: number) => (
                                                        <Form
                                                            key={`${variant}-${idx}`}
                                                            initialValues={
                                                                newExperimentData.parameters?.feature_flag_variants
                                                            }
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
                                                                        defaultValue={variant.key}
                                                                        data-attr="feature-flag-variant-key"
                                                                        data-key-index={idx.toString()}
                                                                        className="ph-ignore-input"
                                                                        style={{ maxWidth: 150 }}
                                                                        placeholder={`example-variant-${idx + 1}`}
                                                                        autoComplete="off"
                                                                        autoCapitalize="off"
                                                                        autoCorrect="off"
                                                                        spellCheck={false}
                                                                    />
                                                                </Form.Item>
                                                                <div className="ml-05">
                                                                    {' '}
                                                                    Roll out to{' '}
                                                                    <InputNumber
                                                                        disabled={true}
                                                                        defaultValue={variant.rollout_percentage}
                                                                        value={variant.rollout_percentage}
                                                                        formatter={(value) => `${value}%`}
                                                                    />{' '}
                                                                    of <b>participants</b>
                                                                </div>
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
                                                    <Button
                                                        style={{
                                                            color: 'var(--primary)',
                                                            border: 'none',
                                                            boxShadow: 'none',
                                                            marginTop: '1rem',
                                                        }}
                                                        icon={<PlusOutlined />}
                                                        onClick={() => addExperimentGroup()}
                                                    >
                                                        Add test group
                                                    </Button>
                                                )}
                                            </Col>
                                        </Col>
                                    )}
                                </Col>
                            </Row>

                            <div>
                                <Row className="metrics-selection">
                                    <BindLogic logic={insightLogic} props={insightProps}>
                                        <Row style={{ width: '100%' }}>
                                            <Col span={8} style={{ paddingRight: 8 }}>
                                                <div className="l3 mb">Goal metric</div>
                                                <Row className="text-muted" style={{ marginBottom: '1rem' }}>
                                                    Define the metric which you are trying to optimize. This is the most
                                                    important part of your experiment.
                                                </Row>
                                                <Row>
                                                    <Card
                                                        className="action-filters-bordered"
                                                        style={{ width: '100%', marginRight: 8 }}
                                                        bodyStyle={{ padding: 0 }}
                                                    >
                                                        <ActionFilter
                                                            filters={filters}
                                                            setFilters={(actionFilters) => {
                                                                setNewExperimentData({ filters: actionFilters })
                                                                setFilters(actionFilters)
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
                                                    </Card>
                                                </Row>
                                            </Col>
                                            <Col span={16}>
                                                <InsightContainer disableTable={true} />
                                            </Col>
                                        </Row>
                                    </BindLogic>
                                </Row>
                            </div>
                            <Card className="experiment-preview">
                                <Row className="preview-row">
                                    <Col>
                                        <div className="card-secondary">Preview</div>
                                        <div>
                                            <span className="mr-05">
                                                <b>{newExperimentData?.name}</b>
                                            </span>
                                            {newExperimentData?.feature_flag_key && (
                                                <CopyToClipboardInline
                                                    explicitValue={newExperimentData.feature_flag_key}
                                                    iconStyle={{ color: 'var(--text-muted-alt)' }}
                                                    description="feature flag key"
                                                >
                                                    <span className="text-muted">
                                                        {newExperimentData.feature_flag_key}
                                                    </span>
                                                </CopyToClipboardInline>
                                            )}
                                        </div>
                                    </Col>
                                </Row>
                                <Row className="preview-row">
                                    <Col span={12}>
                                        <div className="card-secondary">Target Participant Count</div>
                                        <div className="pb">
                                            <span className="l4">~{sampleSize}</span> persons
                                        </div>
                                        <div className="card-secondary">Baseline Conversion Rate</div>
                                        <div className="l4">{conversionRate.toFixed(1)}%</div>
                                    </Col>
                                    <Col span={12}>
                                        <div className="card-secondary">Target duration</div>
                                        <div>
                                            <span className="l4">~{runningTime}</span> days
                                        </div>
                                    </Col>
                                </Row>
                                <Row className="preview-row">
                                    <Col>
                                        <div className="l4">
                                            Conversion goal threshold
                                            <Tooltip
                                                title={`The minimum % change in conversion rate you care about. 
                                                This means you don't care about variants whose
                                                conversion rate is between these two percentages.`}
                                            >
                                                <InfoCircleOutlined style={{ marginLeft: 4 }} />
                                            </Tooltip>
                                        </div>
                                        <div className="pb text-small text-muted">
                                            Apply a threshold to broaden the acceptable range of conversion rates for
                                            this experiment. The acceptable range will be the baseline conversion goal
                                            +/- the goal threshold.
                                        </div>
                                        <div>
                                            <span className="l4 pr">Threshold value</span>
                                            <Slider
                                                min={1}
                                                max={20}
                                                defaultValue={5}
                                                tipFormatter={(value) => `${value}%`}
                                                onChange={(value) =>
                                                    setNewExperimentData({
                                                        parameters: { minimum_detectable_effect: value },
                                                    })
                                                }
                                                marks={{ 5: `5%`, 10: `10%` }}
                                            />
                                        </div>
                                    </Col>
                                </Row>
                                <Row>
                                    <Col>
                                        <div className="card-secondary mb-05">Conversion goal range</div>
                                        <div>
                                            <b>
                                                {Math.max(0, conversionRate - minimumDetectableChange).toFixed()}% -{' '}
                                                {Math.min(100, conversionRate + minimumDetectableChange).toFixed()}%
                                            </b>
                                        </div>
                                    </Col>
                                </Row>
                            </Card>
                        </div>
                        <Button icon={<SaveOutlined />} className="float-right" type="primary" htmlType="submit">
                            Save
                        </Button>
                    </Form>
                </>
            ) : experimentData ? (
                <div className="confirmation">
                    <Row className="draft-header">
                        <Row justify="space-between" align="middle" className="full-width">
                            <Row>
                                <PageHeader style={{ margin: 0, paddingRight: 8 }} title={`${experimentData?.name}`} />
                                <Tag style={{ alignSelf: 'center' }} color={statusColors[status()]}>
                                    <b className="uppercase">{status()}</b>
                                </Tag>
                            </Row>
                            {experimentData && !experimentData.start_date && (
                                <div>
                                    <Button className="mr-05" onClick={() => editExperiment()}>
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
                        </Row>
                        {experimentData.description && <Row>Description: {experimentData.description}</Row>}
                    </Row>
                    <Row>
                        <Col span={10}>
                            <div className="mb-05">
                                <span>Feature flag key:</span> <b>{experimentData.feature_flag_key}</b>
                            </div>
                            <div className="mb-05">
                                Variants:{' '}
                                {experimentData.parameters?.feature_flag_variants?.map(
                                    (variant: MultivariateFlagVariant, idx: number) => (
                                        <li key={idx}>{variant.key}</li>
                                    )
                                )}
                            </div>
                            <div className="mb-05">The following users will participate in the experiment</div>
                            <ul>
                                {experimentData.filters?.properties?.length ? (
                                    experimentData.filters.properties.map((property: PropertyFilter, idx: number) => (
                                        <li key={idx}>
                                            Users with {property.key} {property.operator}{' '}
                                            {Array.isArray(property.value)
                                                ? property.value.map((val) => `${val}, `)
                                                : property.value}
                                        </li>
                                    ))
                                ) : (
                                    <li key={'all users'}>All users</li>
                                )}
                            </ul>
                            <Row>Experiment parameters:</Row>
                            <Row>
                                <ul>
                                    <li>
                                        Recommended running time: ~{experimentData.parameters?.recommended_running_time}{' '}
                                        days
                                    </li>
                                    <li>
                                        Recommended sample size: ~{experimentData.parameters?.recommended_sample_size}{' '}
                                        people
                                    </li>
                                </ul>
                            </Row>
                        </Col>
                        <Col span={14}>
                            <div className="text-default">
                                <Row align="middle">
                                    <b>How to run this experiment in your code</b>
                                    <div className="ml-05">
                                        <CodeLanguageSelect />
                                    </div>
                                </Row>
                                <JSSnippet
                                    variants={['control', 'test']}
                                    flagKey={newExperimentData?.feature_flag_key || ''}
                                />
                                <a
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    href="https://posthog.com/docs/user-guides/feature-flags"
                                >
                                    <Row align="middle">
                                        Learn more about feature flags
                                        <IconOpenInNew className="ml-05" />
                                    </Row>
                                </a>
                            </div>
                            <div className="mt">
                                Test that your code works properly for each variant:{' '}
                                <a
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    href="https://posthog.com/docs/user-guides/feature-flags#develop-locally"
                                >
                                    {' '}
                                    Follow this guide{' '}
                                </a>
                                <div>
                                    For your Feature Flag, the override code looks like:
                                    {['control', 'test'].map((variant) => (
                                        <div key={variant}>
                                            {' '}
                                            {variant}:
                                            <CodeSnippet language={Language.JavaScript}>
                                                {`posthog.feature_flags.override({'${experimentData.feature_flag_key}': '${variant}'})`}
                                            </CodeSnippet>
                                        </div>
                                    ))}
                                </div>
                            </div>
                            <div>Warning: Remember to not change this code until the experiment ends</div>
                        </Col>
                    </Row>
                    {experimentData.start_date && (
                        <div className="experiment-result">
                            {experimentData.end_date && <Alert type="info" message="This experiment has ended" />}
                            <div>Experiment start date: {dayjs(experimentData.start_date).format('D MMM YYYY')}</div>

                            {experimentResults && (
                                <BindLogic
                                    logic={insightLogic}
                                    props={{
                                        dashboardItemId: experimentResults.itemID,
                                        filters: {
                                            ...experimentResults.filters,
                                            insight: 'FUNNELS',
                                            funnel_viz_type: FunnelVizType.Steps,
                                            display: 'FunnelViz',
                                            layout: FunnelLayout.vertical,
                                        },
                                        cachedResults: experimentResults.insight,
                                        syncWithUrl: false,
                                        doNotLoad: true,
                                    }}
                                >
                                    <div>
                                        <PageHeader title="Results" />
                                        <div>
                                            Probability that test has higher conversion than control:{' '}
                                            <b>{(experimentResults?.probability.test * 100).toFixed(1)}%</b>
                                        </div>
                                        {experimentResults.insight?.length === 0 && (
                                            <div className="l4">There were no events related to this experiment.</div>
                                        )}

                                        <div>
                                            Test variant conversion rate: <b>{conversionRateForVariant('test')}</b>
                                        </div>
                                        <div>
                                            Control variant conversion rate:{' '}
                                            <b>{conversionRateForVariant('control')}</b>
                                        </div>
                                        <InsightContainer disableTable={true} />
                                    </div>
                                </BindLogic>
                            )}
                        </div>
                    )}
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
