import '../Experiment.scss'

import { useValues } from 'kea'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils'

import { InsightType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { formatUnitByQuantity } from '../utils'

export function ProgressBar(): JSX.Element {
    const {
        experiment,
        experimentInsightType,
        funnelResultsPersonsTotal,
        recommendedSampleSize,
        actualRunningTime,
        recommendedRunningTime,
    } = useValues(experimentLogic)

    const experimentProgressPercent =
        experimentInsightType === InsightType.FUNNELS
            ? (funnelResultsPersonsTotal / recommendedSampleSize) * 100
            : (actualRunningTime / recommendedRunningTime) * 100

    return (
        <div>
            <h2 className="font-semibold text-lg mb-0">Data collection</h2>
            <div className="text-muted text-xs">
                Estimated target for the number of participants. Actual data may reveal significance earlier or later
                than predicted.
            </div>
            <div className="mt-4 mb-1 font-semibold">{`${
                experimentProgressPercent > 100 ? 100 : experimentProgressPercent.toFixed(2)
            }% complete`}</div>
            <LemonProgress
                className="w-full border"
                bgColor="var(--bg-table)"
                size="large"
                percent={experimentProgressPercent}
            />
            {experimentInsightType === InsightType.TRENDS && experiment.start_date && (
                <div className="flex justify-between mt-2">
                    {experiment.end_date ? (
                        <div>
                            Ran for <b>{actualRunningTime}</b> {formatUnitByQuantity(actualRunningTime, 'day')}
                        </div>
                    ) : (
                        <div>
                            <b>{actualRunningTime}</b> {formatUnitByQuantity(actualRunningTime, 'day')} running
                        </div>
                    )}
                    <div>
                        Goal: <b>{recommendedRunningTime}</b> {formatUnitByQuantity(recommendedRunningTime, 'day')}
                    </div>
                </div>
            )}
            {experimentInsightType === InsightType.FUNNELS && (
                <div className="flex justify-between mt-2">
                    {experiment.end_date ? (
                        <div>
                            Saw <b>{humanFriendlyNumber(funnelResultsPersonsTotal)}</b>{' '}
                            {formatUnitByQuantity(funnelResultsPersonsTotal, 'participant')}
                        </div>
                    ) : (
                        <div>
                            <b>{humanFriendlyNumber(funnelResultsPersonsTotal)}</b>{' '}
                            {formatUnitByQuantity(funnelResultsPersonsTotal, 'participant')} seen
                        </div>
                    )}
                    <div>
                        Goal: <b>{humanFriendlyNumber(recommendedSampleSize)}</b>{' '}
                        {formatUnitByQuantity(recommendedSampleSize, 'participant')}
                    </div>
                </div>
            )}
        </div>
    )
}
