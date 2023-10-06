import { LemonTable } from '@posthog/lemon-ui'
import { SurveyUserStats } from './surveyLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

const formatCount = (count: number, total: number): string => {
    if ((count / total) * 100 < 3) {
        return ''
    }
    return `${count}`
}

export function UsersCount({ surveyUserStats }: { surveyUserStats: SurveyUserStats }): JSX.Element {
    const { seen, dismissed, sent } = surveyUserStats
    const total = seen + dismissed + sent
    const labelTotal = total === 1 ? 'Unique user viewed' : 'Unique users viewed'
    const labelSent = sent === 1 ? 'Response submitted' : 'Responses submitted'

    return (
        <div className="inline-flex mb-4">
            <div>
                <div className="text-4xl font-bold">{total}</div>
                <div className="font-semibold text-muted-alt">{labelTotal}</div>
            </div>
            {sent > 0 && (
                <div className="ml-10">
                    <div className="text-4xl font-bold">{sent}</div>
                    <div className="font-semibold text-muted-alt">{labelSent}</div>
                </div>
            )}
        </div>
    )
}

export function UsersStackedBar({ surveyUserStats }: { surveyUserStats: SurveyUserStats }): JSX.Element {
    const { seen, dismissed, sent } = surveyUserStats

    const total = seen + dismissed + sent
    const seenPercentage = (seen / total) * 100
    const dismissedPercentage = (dismissed / total) * 100
    const sentPercentage = (sent / total) * 100

    return (
        <>
            {total > 0 && (
                <div className="mb-6">
                    <div className="w-full mx-auto h-10 mb-4">
                        {[
                            {
                                count: seen,
                                label: 'Viewed',
                                classes: `bg-primary rounded-l ${dismissed === 0 && sent === 0 ? 'rounded-r' : ''}`,
                                style: { width: `${seenPercentage}%` },
                            },
                            {
                                count: dismissed,
                                label: 'Dismissed',
                                classes: `${seen === 0 ? 'rounded-l' : ''} ${sent === 0 ? 'rounded-r' : ''}`,
                                style: {
                                    backgroundColor: '#E3A506',
                                    width: `${dismissedPercentage}%`,
                                    left: `${seenPercentage}%`,
                                },
                            },
                            {
                                count: sent,
                                label: 'Submitted',
                                classes: `rounded-r ${seen === 0 && dismissed === 0 ? 'rounded-l' : ''}`,
                                style: {
                                    backgroundColor: '#529B08',
                                    width: `${sentPercentage}%`,
                                    left: `${seenPercentage + dismissedPercentage}%`,
                                },
                            },
                        ].map(({ count, label, classes, style }) => (
                            <Tooltip
                                key={`survey-summary-chart-${label}`}
                                title={`${label} surveys: ${count}`}
                                delayMs={0}
                                placement="top"
                            >
                                <div
                                    className={`h-10 text-white text-center absolute cursor-pointer ${classes}`}
                                    style={style}
                                >
                                    <span className="inline-flex font-semibold max-w-full px-1 truncate leading-10">
                                        {formatCount(count, total)}
                                    </span>
                                </div>
                            </Tooltip>
                        ))}
                    </div>
                    <div className="w-full flex justify-center">
                        <div className="flex items-center">
                            {[
                                { count: seen, label: 'Viewed', color: 'bg-primary' },
                                { count: dismissed, label: 'Dismissed', color: 'bg-warning' },
                                { count: sent, label: 'Submitted', color: 'bg-success' },
                            ].map(({ count, label, color }) => (
                                <div key={`survey-summary-legend-${label}`} className="flex items-center mr-6">
                                    <div className={`w-3 h-3 rounded-full mr-2 ${color}`} />
                                    <span className="font-semibold text-muted-alt">{`${label} (${(
                                        (count / total) *
                                        100
                                    ).toFixed(1)}%)`}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </>
    )
}

export function Summary({
    surveyUserStats,
    surveyUserStatsLoading,
}: {
    surveyUserStats: SurveyUserStats
    surveyUserStatsLoading: boolean
}): JSX.Element {
    if (!surveyUserStats) {
        return <></>
    }

    return (
        <div className="mb-4">
            {surveyUserStatsLoading ? (
                <LemonTable dataSource={[]} columns={[]} loading={true} />
            ) : (
                <>
                    <UsersCount surveyUserStats={surveyUserStats} />
                    <UsersStackedBar surveyUserStats={surveyUserStats} />
                </>
            )}
        </div>
    )
}
