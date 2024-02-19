import './Experiment.scss'

import { IconPlusSmall, IconTrash, IconWarning } from '@posthog/icons'
import {
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonTag,
    LemonTagType,
    LemonTextArea,
    Tooltip,
} from '@posthog/lemon-ui'
import { Popconfirm } from 'antd'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { router } from 'kea-router'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Link } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter, humanFriendlyNumber } from 'lib/utils'
import { useEffect, useState } from 'react'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Query } from '~/queries/Query/Query'
import { AvailableFeature, Experiment as ExperimentType, FunnelStep, InsightType, ProgressStatus } from '~/types'

import { EXPERIMENT_INSIGHT_ID } from './constants'
import { ExperimentImplementationDetails } from './ExperimentImplementationDetails'
import { experimentLogic, ExperimentLogicProps } from './experimentLogic'
import { ExperimentPreview } from './ExperimentPreview'
import { ExperimentResult } from './ExperimentResult'
import { getExperimentStatus, getExperimentStatusColor } from './experimentsLogic'
import { ExperimentsPayGate } from './ExperimentsPayGate'
import { ExperimentInsightCreator } from './MetricSelector'
import { SecondaryMetrics } from './SecondaryMetrics'

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
                <PageHeader />
                <ExperimentsPayGate />
            </>
        )
    }

    if (experimentLoading) {
        return <LoadingState />
    }

    if (experimentMissing) {
        return <NotFound object="experiment" />
    }

    return (
        <>
            {experimentId === 'new' || editingExistingExperiment ? (
                <>
                    <Form
                        id="experiment"
                        logic={experimentLogic}
                        formKey="experiment"
                        props={props}
                        enableFormOnSubmit
                        className="space-y-4 experiment-form"
                    >
                        <PageHeader
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
                                        form="experiment"
                                    >
                                        {editingExistingExperiment ? 'Save' : 'Save as draft'}
                                    </LemonButton>
                                </div>
                            }
                        />
                        <LemonDivider />

                        <BindLogic logic={insightLogic} props={insightProps}>
                            <>
                                <div className="flex flex-col gap-2 max-w-1/2">
                                    <LemonField name="name" label="Name">
                                        <LemonInput data-attr="experiment-name" />
                                    </LemonField>
                                    <LemonField name="feature_flag_key" label="Feature flag key">
                                        <LemonInput
                                            data-attr="experiment-feature-flag-key"
                                            disabled={editingExistingExperiment}
                                        />
                                    </LemonField>
                                    <LemonField
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
                                    </LemonField>
                                    {experiment.parameters.feature_flag_variants && (
                                        <div>
                                            <label>
                                                <b>Experiment variants</b>
                                            </label>
                                            <div className="text-muted">
                                                Participants are divided into variant groups evenly. All experiments
                                                must consist of a control group and at least one test group. Experiments
                                                may have at most 9 test groups. Variant names can only contain letters,
                                                numbers, hyphens, and underscores.
                                            </div>
                                            <div className="variants">
                                                {experiment.parameters.feature_flag_variants?.map((_, index) => (
                                                    <Group
                                                        key={index}
                                                        name={['parameters', 'feature_flag_variants', index]}
                                                    >
                                                        <div
                                                            key={`variant-${index}`}
                                                            className={clsx(
                                                                'feature-flag-variant',
                                                                index === 0
                                                                    ? 'border-t'
                                                                    : index >= maxVariants
                                                                    ? 'border-b'
                                                                    : ''
                                                            )}
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
                                                            <LemonField name="key" className="extend-variant-fully">
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
                                                            </LemonField>

                                                            <div className="float-right">
                                                                {experimentId === 'new' &&
                                                                    !(index === 0 || index === 1) && (
                                                                        <Tooltip
                                                                            title="Delete this variant"
                                                                            placement="bottom-start"
                                                                        >
                                                                            <LemonButton
                                                                                size="small"
                                                                                icon={<IconTrash />}
                                                                                onClick={() =>
                                                                                    removeExperimentGroup(index)
                                                                                }
                                                                            />
                                                                        </Tooltip>
                                                                    )}
                                                            </div>
                                                        </div>
                                                    </Group>
                                                ))}

                                                {(experiment.parameters.feature_flag_variants.length ?? 0) <
                                                    maxVariants &&
                                                    experimentId === 'new' && (
                                                        <div className="feature-flag-variant border-b">
                                                            <LemonButton
                                                                onClick={() => addExperimentGroup()}
                                                                icon={<IconPlusSmall />}
                                                                data-attr="add-test-variant"
                                                            >
                                                                Add test variant
                                                            </LemonButton>
                                                        </div>
                                                    )}
                                            </div>
                                        </div>
                                    )}
                                </div>
                                <div className="person-selection">
                                    <div className="max-w-1/2">
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
                                    </div>
                                </div>

                                <div className="flex metrics-selection gap-4">
                                    <div className="flex-1">
                                        <div className="mb-2" data-attr="experiment-goal-type">
                                            <b>Goal type</b>
                                            <div className="text-muted">
                                                {experimentInsightType === InsightType.TRENDS
                                                    ? 'Track counts of a specific event or action'
                                                    : 'Track how many persons complete a sequence of actions and or events'}
                                            </div>
                                        </div>
                                        <LemonSelect
                                            data-attr="experiment-goal-type-select"
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
                                    </div>
                                    <div className="flex-1">
                                        <div className="card-secondary mb-4" data-attr="experiment-preview">
                                            Goal preview
                                        </div>
                                        <BindLogic logic={insightLogic} props={insightProps}>
                                            <Query query={query} context={{ insightProps }} readOnly />
                                        </BindLogic>
                                    </div>
                                </div>
                                <LemonField name="secondary_metrics">
                                    {({ value, onChange }) => (
                                        <div className="secondary-metrics">
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
                                        </div>
                                    )}
                                </LemonField>
                                <div className="bg-bg-light border rounded experiment-preview p-4">
                                    <ExperimentPreview
                                        experimentId={experiment.id}
                                        trendCount={trendCount}
                                        trendExposure={exposure}
                                        funnelSampleSize={sampleSize}
                                        funnelEntrants={entrants}
                                        funnelConversionRate={conversionRate}
                                    />
                                </div>
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
                                form="experiment"
                            >
                                {editingExistingExperiment ? 'Save' : 'Save as draft'}
                            </LemonButton>
                        </div>
                    </Form>
                </>
            ) : experiment ? (
                <div className="view-experiment">
                    <div className="draft-header">
                        <PageHeader
                            buttons={
                                <>
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
                                                <LemonButton type="secondary">Reset</LemonButton>
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
                                </>
                            }
                        />
                        <div className="w-full pb-4">
                            <div className="inline-flex">
                                <div className="block">
                                    <div className="exp-flag-copy-label">Status</div>
                                    <StatusTag experiment={experiment} />
                                    <span className="ml-2">
                                        <ResultsTag />
                                    </span>
                                </div>
                                {experiment.feature_flag && (
                                    <div className="block ml-10">
                                        <div className="exp-flag-copy-label">Feature flag</div>
                                        {getExperimentStatus(experiment) === ProgressStatus.Running &&
                                            !experiment.feature_flag.active && (
                                                <Tooltip
                                                    placement="bottom"
                                                    title="Your experiment is running, but the linked flag is disabled. No data is being collected."
                                                >
                                                    <IconWarning
                                                        style={{ transform: 'translateY(2px)' }}
                                                        className="mr-1 text-danger"
                                                        fontSize="18px"
                                                    />
                                                </Tooltip>
                                            )}
                                        <CopyToClipboardInline
                                            iconStyle={{ color: 'var(--lemon-button-icon-opacity)' }}
                                            className="font-normal text-sm"
                                            description="feature flag key"
                                        >
                                            {experiment.feature_flag.key}
                                        </CopyToClipboardInline>
                                    </div>
                                )}
                            </div>
                            <div className="mt-6 exp-description">
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
                            </div>
                        </div>
                    </div>
                    <div className="mb-4">
                        {showWarning && experimentResults && areResultsSignificant && !experiment.end_date && (
                            <LemonBanner
                                className="w-full"
                                type="success"
                                onClose={experiment.end_date ? () => setShowWarning(false) : undefined}
                                action={
                                    !experiment.end_date
                                        ? {
                                              onClick: () => endExperiment(),
                                              type: 'primary',
                                              children: 'End experiment',
                                          }
                                        : undefined
                                }
                            >
                                <div>
                                    Experiment results are significant.{' '}
                                    {experiment.end_date
                                        ? ''
                                        : 'You can end your experiment now or let it run until complete.'}
                                </div>
                            </LemonBanner>
                        )}
                        {showWarning && experimentResults && !areResultsSignificant && !experiment.end_date && (
                            <LemonBanner type="warning" onClose={() => setShowWarning(false)}>
                                <strong>Your results are not statistically significant</strong>.{' '}
                                {significanceBannerDetails}{' '}
                                {experiment?.end_date ? '' : "We don't recommend ending this experiment yet."} See our{' '}
                                <Link to="https://posthog.com/docs/user-guides/experimentation#funnel-experiment-calculations">
                                    {' '}
                                    experimentation guide{' '}
                                </Link>
                                for more information.{' '}
                            </LemonBanner>
                        )}
                        {showWarning && experiment.end_date && experiment.feature_flag?.active && (
                            <LemonBanner type="info" onClose={() => setShowWarning(false)}>
                                <strong>Your experiment is complete, but the feature flag is still enabled.</strong> We
                                recommend removing the feature flag from your code completely, instead of relying on
                                this distribution.{' '}
                                <Link
                                    to={
                                        experiment.feature_flag
                                            ? urls.featureFlag(experiment.feature_flag.id)
                                            : undefined
                                    }
                                >
                                    <b>Adjust feature flag distribution</b>
                                </Link>
                            </LemonBanner>
                        )}
                    </div>
                    <div>
                        <LemonCollapse
                            className="w-full"
                            defaultActiveKey="experiment-details"
                            panels={[
                                {
                                    key: 'experiment-details',
                                    header: 'Experiment details',
                                    content: (
                                        <div>
                                            <div className={isExperimentRunning ? 'w-1/2' : 'w-full'}>
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
                                            </div>
                                            {!experimentResultsLoading && !experimentResults && isExperimentRunning && (
                                                <div className="w-1/2">
                                                    <ExperimentImplementationDetails experiment={experiment} />
                                                </div>
                                            )}
                                            {experimentResults && (
                                                <div className="w-1/2 mt-4">
                                                    <div className="mb-2">
                                                        <b>Experiment progress</b>
                                                    </div>
                                                    <LemonProgress
                                                        size="large"
                                                        percent={experimentProgressPercent}
                                                        strokeColor="var(--success)"
                                                    />
                                                    {experimentInsightType === InsightType.TRENDS &&
                                                        experiment.start_date && (
                                                            <div className="flex justify-between mt-2">
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
                                                            </div>
                                                        )}
                                                    {experimentInsightType === InsightType.FUNNELS && (
                                                        <div className="flex justify-between mt-2">
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
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                            <div>
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
                                            </div>
                                        </div>
                                    ),
                                },
                            ]}
                        />
                        {experiment && !experiment.start_date && (
                            <div className="mt-4 w-full">
                                <ExperimentImplementationDetails experiment={experiment} />
                            </div>
                        )}
                    </div>
                    <ExperimentResult />
                </div>
            ) : (
                <LoadingState />
            )}
        </>
    )
}

export function StatusTag({ experiment }: { experiment: ExperimentType }): JSX.Element {
    const status = getExperimentStatus(experiment)
    return (
        <LemonTag type={getExperimentStatusColor(status)}>
            <b className="uppercase">{status}</b>
        </LemonTag>
    )
}

export function ResultsTag(): JSX.Element {
    const { experiment, experimentResults, areResultsSignificant } = useValues(experimentLogic)
    if (experimentResults && experiment.end_date) {
        const result: { color: LemonTagType; label: string } = areResultsSignificant
            ? { color: 'success', label: 'Significant Results' }
            : { color: 'primary', label: 'Results not significant' }

        return (
            <LemonTag type={result.color}>
                <b className="uppercase">{result.label}</b>
            </LemonTag>
        )
    }

    return <></>
}

export function LoadingState(): JSX.Element {
    return (
        <div className="space-y-4">
            <LemonSkeleton className="w-1/3 h-4" />
            <LemonSkeleton />
            <LemonSkeleton />
            <LemonSkeleton className="w-2/3 h-4" />
        </div>
    )
}
