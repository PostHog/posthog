import { useValues } from 'kea'

import { IconGraph } from '@posthog/icons'
import { LemonCollapse, LemonSkeleton } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { DailyVolumeChart } from '../DailyVolumeChart'
import { ProbabilityHistogram } from '../ProbabilityHistogram'
import { EmptyTab } from './EmptyTab'
import { PredictionActionsPanel } from './PredictionActionsPanel'
import { CoverageHistoryChart, CoverageSummaryBanner } from './PredictionCoverage'
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
    const { probabilityHistogram, probabilityDistributionError, segmentThresholds } =
        useValues(autoresearchPipelineLogic)

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
    return <ProbabilityHistogram buckets={probabilityHistogram} thresholds={segmentThresholds} />
}

export function PredictionsTab(): JSX.Element {
    const { pipeline } = useValues(autoresearchPipelineLogic)
    if (!pipeline) {
        return <LemonSkeleton className="h-40" />
    }

    if (!pipeline.last_scored_at) {
        return (
            <EmptyTab icon={<IconGraph />} title="No predictions yet" cta={<ScoreNowButton />}>
                Once the live model scores your inference population, each person's predicted probability is recorded as
                an <code>autoresearch_prediction</code> event.
                {pipeline.write_person_property && (
                    <>
                        {' '}
                        It is also written to the <code>{pipeline.output_person_property}</code> person property.
                    </>
                )}{' '}
                Score now to populate this tab.
            </EmptyTab>
        )
    }

    return (
        <div className="space-y-6">
            <CoverageSummaryBanner />

            <SectionCard
                title="Likelihood segments"
                description={
                    <>
                        Each scoring run records every person's predicted probability as an{' '}
                        <code>autoresearch_prediction</code> event.
                        {pipeline.write_person_property && (
                            <>
                                {' '}
                                It also writes the score to the <code>{pipeline.output_person_property}</code> person
                                property.
                            </>
                        )}{' '}
                        These views read from those events.
                    </>
                }
            >
                <PredictionSegmentCards />
            </SectionCard>

            <PredictionActionsPanel />

            <LemonCollapse
                className="bg-surface-primary"
                multiple
                defaultActiveKeys={['distribution', 'people']}
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
                        content: <CoverageHistoryChart />,
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
