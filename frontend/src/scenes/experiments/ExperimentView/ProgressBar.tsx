import '../Experiment.scss'

import { useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils'

import { FunnelStep, InsightType } from '~/types'

import { experimentLogic } from '../experimentLogic'

export function ProgressBar(): JSX.Element {
    const { experiment, experimentResults, experimentInsightType } = useValues(experimentLogic)

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

    return (
        <div>
            <div className="mb-1 font-semibold">{`${
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
                            Ran for <b>{dayjs(experiment.end_date).diff(experiment.start_date, 'day')}</b> days
                        </div>
                    ) : (
                        <div>
                            <b>{dayjs().diff(experiment.start_date, 'day')}</b> days running
                        </div>
                    )}
                    <div>
                        Goal: <b>{experiment?.parameters?.recommended_running_time ?? 'Unknown'}</b> days
                    </div>
                </div>
            )}
            {experimentInsightType === InsightType.FUNNELS && (
                <div className="flex justify-between mt-2">
                    {experiment.end_date ? (
                        <div>
                            Saw <b>{humanFriendlyNumber(funnelResultsPersonsTotal)}</b> participants
                        </div>
                    ) : (
                        <div>
                            <b>{humanFriendlyNumber(funnelResultsPersonsTotal)}</b> participants seen
                        </div>
                    )}
                    <div>
                        Goal: <b>{humanFriendlyNumber(experiment?.parameters?.recommended_sample_size || 0)}</b>{' '}
                        participants
                    </div>
                </div>
            )}
        </div>
    )
}
