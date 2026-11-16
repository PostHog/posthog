import { useActions, useValues } from 'kea'

import { IconGraph } from '@posthog/icons'
import { LemonBanner, LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { accuracyStats, checkedDateRange, holdoutSentence } from '../onlinePerformance'
import { AccuracyTrendCard } from './AccuracyTrendCard'
import { CheckedDatesHistory } from './CheckedDatesHistory'
import { ConfusionMatrixCard } from './ConfusionMatrixCard'
import { EmptyTab } from './EmptyTab'
import { LiveModelDrivers } from './LiveModelDrivers'
import { MetricCard } from './MetricCard'
import { ScoreNowButton } from './ScoreNowButton'
import { SectionCard } from './SectionCard'
import { SegmentCalibrationBars } from './SegmentCalibrationBars'

function NotCheckedYet(): JSX.Element {
    const { pipeline, firstCheck } = useValues(autoresearchPipelineLogic)
    const horizon = pluralize(pipeline?.horizon_days ?? 0, 'day')
    return (
        <EmptyTab icon={<IconGraph />} title="Not checked against real outcomes yet" cta={<ScoreNowButton />}>
            PostHog checks each prediction against what people really did, {horizon} after the prediction.{' '}
            {!firstCheck
                ? `Score the model to start. The first check comes ${horizon} after the first scoring run.`
                : firstCheck.isAfter(dayjs())
                  ? `The first check is due on ${firstCheck.format('MMM D, YYYY')}.`
                  : `The first scored date matured on ${firstCheck.format('MMM D, YYYY')}. The first check runs on the next daily schedule.`}
        </EmptyTab>
    )
}

export function OnlinePerformanceTab(): JSX.Element {
    const {
        pipeline,
        champion,
        onlinePerformance,
        onlinePerformanceLoading,
        onlinePerformanceError,
        liveModelPerformance,
        accuracyFrame,
        accuracyFrameRows,
        rankCalibration,
    } = useValues(autoresearchPipelineLogic)
    const { loadOnlinePerformance, setAccuracyFrame } = useActions(autoresearchPipelineLogic)

    if (onlinePerformanceLoading && onlinePerformance.length === 0) {
        return <Spinner />
    }

    if (onlinePerformanceError) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Retry',
                    onClick: () => loadOnlinePerformance(),
                    'data-attr': 'autoresearch-model-accuracy-retry',
                }}
            >
                Couldn't load this model's accuracy. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }

    if (liveModelPerformance.length === 0 || !pipeline) {
        return (
            <div className="space-y-6">
                <NotCheckedYet />
                <LiveModelDrivers />
                <CheckedDatesHistory />
            </div>
        )
    }

    const multiDate = accuracyFrameRows.length > 1
    const predictions = accuracyFrameRows.reduce((total, row) => total + row.n_scored, 0)
    const holdout = holdoutSentence(accuracyFrameRows, champion?.holdout_score ?? null)

    return (
        <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
                {liveModelPerformance.length > 1 && (
                    <LemonSegmentedButton
                        size="small"
                        value={accuracyFrame}
                        onChange={setAccuracyFrame}
                        options={[
                            {
                                value: 'all',
                                label: `All ${liveModelPerformance.length} checked dates`,
                                'data-attr': 'autoresearch-model-accuracy-frame-all',
                            },
                            {
                                value: 'latest',
                                label: `Latest: ${dayjs(liveModelPerformance[0].prediction_date).format('MMM D')}`,
                                'data-attr': 'autoresearch-model-accuracy-frame-latest',
                            },
                        ]}
                    />
                )}
                <span className="text-xs text-secondary">
                    {checkedDateRange(accuracyFrameRows)} ·{' '}
                    {multiDate ? pluralize(predictions, 'prediction') : pluralize(predictions, 'person', 'people')}
                </span>
            </div>

            <SectionCard>
                <div className="@container">
                    <div className="grid grid-cols-1 @sm:grid-cols-2 @3xl:grid-cols-4 gap-2">
                        {accuracyStats(accuracyFrameRows, pipeline.target_event).map(({ key, ...stat }) => (
                            <MetricCard key={key} {...stat} />
                        ))}
                    </div>
                </div>
                {holdout && <p className="text-sm mb-0">{holdout}</p>}
            </SectionCard>

            <ConfusionMatrixCard />

            {rankCalibration.length > 0 && (
                <SectionCard
                    title="Predicted and actual rate"
                    description="People ranked by score, in groups of 10% of everyone scored."
                >
                    <SegmentCalibrationBars groups={rankCalibration} unit={multiDate ? 'prediction' : 'person'} />
                </SectionCard>
            )}

            <AccuracyTrendCard />

            <LiveModelDrivers />

            <CheckedDatesHistory />
        </div>
    )
}
