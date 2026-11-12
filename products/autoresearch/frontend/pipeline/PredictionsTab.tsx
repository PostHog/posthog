import { useActions, useValues } from 'kea'

import { IconGraph } from '@posthog/icons'
import { LemonCollapse, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { DailyVolumeChart } from '../DailyVolumeChart'
import { ProbabilityHistogram } from '../ProbabilityHistogram'
import { EmptyTab } from './EmptyTab'
import { PredictionActionsPanel } from './PredictionActionsPanel'
import {
    COVERAGE_PANEL_DATA_ATTR,
    CoverageHistoryChart,
    CoverageSummaryBanner,
    LowCoverageNotice,
} from './PredictionCoverage'
import { PredictionSegmentCards } from './PredictionSegmentCards'
import { ProbabilityUsersTable } from './ProbabilityUsersTable'
import { ScoreNowButton } from './ScoreNowButton'
import { SectionCard } from './SectionCard'

function DailyVolumePanel(): JSX.Element {
    const { dailyVolume, dailyVolumeError } = useValues(autoresearchPipelineLogic)

    if (dailyVolumeError) {
        return (
            <p className="text-sm text-muted mb-0">Couldn't load the scoring volume. Refresh the page to try again.</p>
        )
    }
    if (dailyVolume == null) {
        return <LemonSkeleton className="h-44" />
    }
    if (dailyVolume.length === 0) {
        return (
            <p className="text-sm text-muted mb-0">No prediction events found. Score now to emit fresh predictions.</p>
        )
    }
    return <DailyVolumeChart points={dailyVolume} />
}

function ProbabilityDistributionPanel(): JSX.Element {
    const { probabilityHistogram, probabilityDistributionError, segmentThresholds, lowestBucket, lowestBucketHidden } =
        useValues(autoresearchPipelineLogic)
    const { setHideLowestBucket } = useActions(autoresearchPipelineLogic)

    if (probabilityDistributionError) {
        return (
            <p className="text-sm text-muted mb-0">
                Couldn't load the probability distribution. Refresh the page to try again.
            </p>
        )
    }
    if (probabilityHistogram == null) {
        return <LemonSkeleton className="h-52" />
    }
    if (probabilityHistogram.every((bucket) => bucket.users === 0)) {
        return (
            <p className="text-sm text-muted mb-0">
                No prediction events found for the latest scoring run. Score now to emit fresh predictions.
            </p>
        )
    }
    return (
        <div className="space-y-3">
            {lowestBucket && (
                <LemonSwitch
                    label="Hide the lowest bucket"
                    checked={lowestBucketHidden}
                    onChange={setHideLowestBucket}
                    data-attr="autoresearch-hide-lowest-bucket"
                />
            )}
            <ProbabilityHistogram
                buckets={probabilityHistogram}
                thresholds={segmentThresholds}
                hideLowestBucket={lowestBucketHidden}
            />
            {lowestBucketHidden && lowestBucket && (
                <p className="text-xs text-muted mb-0">
                    {`The 0-10% bucket is hidden. It holds ${humanFriendlyNumber(lowestBucket.users)} people (${(100 * lowestBucket.share).toFixed(1)}% of everyone scored).`}
                </p>
            )}
        </div>
    )
}

export function PredictionsTab(): JSX.Element {
    const { pipeline, predictionsPanels } = useValues(autoresearchPipelineLogic)
    const { setPredictionsPanels } = useActions(autoresearchPipelineLogic)
    if (!pipeline) {
        return <LemonSkeleton className="h-40" />
    }

    if (!pipeline.last_scored_at) {
        return (
            <EmptyTab icon={<IconGraph />} title="No predictions yet" cta={<ScoreNowButton />}>
                Once the champion scores your inference population, each user's predicted probability lands on the{' '}
                <code>{pipeline.output_person_property}</code> person property and an{' '}
                <code>autoresearch_prediction</code> event is emitted. Score now to populate this tab.
            </EmptyTab>
        )
    }

    return (
        <div className="space-y-6">
            <LowCoverageNotice />

            <SectionCard
                title="Likelihood segments"
                description={
                    <>
                        Each scoring run writes the champion's predicted probability to the{' '}
                        <code>{pipeline.output_person_property}</code> person property and emits an{' '}
                        <code>autoresearch_prediction</code> event. These views read straight from those events.
                    </>
                }
            >
                <PredictionSegmentCards />
            </SectionCard>

            <PredictionActionsPanel />

            <LemonCollapse
                className="bg-surface-primary"
                multiple
                activeKeys={predictionsPanels}
                onChange={setPredictionsPanels}
                panels={[
                    {
                        key: 'distribution',
                        header: 'Probability distribution (latest scoring run)',
                        content: <ProbabilityDistributionPanel />,
                    },
                    {
                        key: 'people',
                        header: 'People (latest scoring run)',
                        content: <ProbabilityUsersTable pipelineId={pipeline.id} />,
                    },
                    {
                        key: 'coverage',
                        header: 'Coverage and score age',
                        dataAttr: COVERAGE_PANEL_DATA_ATTR,
                        content: (
                            <div className="space-y-4">
                                <CoverageSummaryBanner />
                                <CoverageHistoryChart />
                            </div>
                        ),
                    },
                    {
                        key: 'volume',
                        header: 'Daily scoring volume',
                        content: <DailyVolumePanel />,
                    },
                ]}
            />
        </div>
    )
}
