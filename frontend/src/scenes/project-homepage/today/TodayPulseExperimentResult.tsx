import { Heading, Text } from '@posthog/quill'

import type { HighlightExperimentResultApi } from 'products/today/frontend/generated/api.schemas'

import { TodayChange } from './TodayChange'
import {
    experimentComparison,
    experimentExposures,
    experimentLiftDecimals,
    experimentVerdict,
} from './todayPulseExperiment'
import type { TodayTone } from './todayTone'

export function TodayPulseExperimentResult({
    lift,
    experiment,
    tone,
}: {
    lift: number
    experiment: HighlightExperimentResultApi
    tone: TodayTone
}): JSX.Element {
    return (
        <>
            <Text size="xs" variant="muted" render={<span />} className="line-clamp-2">
                {experiment.metric_name}
            </Text>
            <div className="flex flex-wrap items-baseline gap-x-2">
                <Heading size="xl" render={<span />} className="tabular-nums">
                    <TodayChange change={lift} tone={tone} decimals={experimentLiftDecimals(lift)} />
                </Heading>
                <span className="min-w-0 text-sm text-muted-foreground wrap-anywhere">
                    {experimentComparison(experiment)}
                </span>
            </div>
            <Text size="xs" variant="muted" render={<span />}>
                {`${experimentVerdict(experiment)} · ${experimentExposures(experiment)}`}
            </Text>
        </>
    )
}
