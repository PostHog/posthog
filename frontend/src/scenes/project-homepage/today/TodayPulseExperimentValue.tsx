import './Today.scss'

import type { HighlightExperimentResultApi } from 'products/today/frontend/generated/api.schemas'

import { TodayChange } from './TodayChange'
import { experimentComparison, experimentLiftDecimals, experimentVerdict } from './todayPulseExperiment'
import type { TodayTone } from './todayTone'

export function TodayPulseExperimentValue({
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
            <span className="TodayPulse__row">
                <span className="TodayPulse__value">
                    <TodayChange change={lift} tone={tone} decimals={experimentLiftDecimals(lift)} />
                </span>
                <span className="TodayChange min-w-0 truncate">{experimentComparison(experiment)}</span>
            </span>
            <span className="TodayPulse__verdict">{experimentVerdict(experiment)}</span>
        </>
    )
}
