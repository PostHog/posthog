import { useValues } from 'kea'

import { IconGraph } from '@posthog/icons'
import { LemonBanner, LemonCollapse, LemonSkeleton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { DailyVolumeChart } from '../DailyVolumeChart'
import { ProbabilityHistogram } from '../ProbabilityHistogram'
import { EmptyTab } from './EmptyTab'
import { ProbabilityUsersTable } from './ProbabilityUsersTable'
import { ScoreNowButton } from './ScoreNowButton'

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
    const { probabilityHistogram, probabilityDistributionError } = useValues(autoresearchPipelineLogic)

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
    return <ProbabilityHistogram buckets={probabilityHistogram} />
}

function ScoringCoverageBanner(): JSX.Element | null {
    const { scoringCoverage } = useValues(autoresearchPipelineLogic)
    if (!scoringCoverage) {
        return null
    }
    const { scored, eligible, rescoreDays } = scoringCoverage
    return (
        <LemonBanner type="info">
            The latest run scored {humanFriendlyNumber(scored)} of {humanFriendlyNumber(eligible)} users, starting with
            users never scored, then those scored longest ago. Everyone is rescored about every {rescoreDays} days.
        </LemonBanner>
    )
}

export function PredictionsTab(): JSX.Element {
    const { pipeline } = useValues(autoresearchPipelineLogic)
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
            <p className="text-sm text-muted">
                Each scoring run writes the champion's predicted probability to the{' '}
                <code>{pipeline.output_person_property}</code> person property and emits an{' '}
                <code>autoresearch_prediction</code> event. These views read straight from those events.
            </p>

            <ScoringCoverageBanner />

            <LemonCollapse
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
                        key: 'volume',
                        header: 'Daily scoring volume',
                        content: <DailyVolumePanel />,
                    },
                ]}
            />
        </div>
    )
}
