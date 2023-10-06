import { LemonTable } from '@posthog/lemon-ui'
import { SurveyUserStats } from './surveyLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

const formatPercentageValue = (value: number): string => {
    if (value < 5) {
        return ''
    }
    return `${value.toFixed(1)}%`
}

export function UsersCount({ surveyUserStats }: { surveyUserStats: SurveyUserStats }): JSX.Element {
    if (!surveyUserStats) {
        return <></>
    }

    const { seen, dismissed, sent } = surveyUserStats
    const total = seen + dismissed + sent
    const label = total === 1 ? 'Unique user viewed' : 'Unique users viewed'

    return (
        <div className="mb-4">
            <div className="text-4xl font-bold">{total}</div>
            <div className="font-semibold text-muted-alt">{label}</div>
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
        <div className="mb-6">
            <div className="w-full mx-auto h-8 mb-4">
                {[
                    {
                        value: seenPercentage,
                        label: 'Seen',
                        classes: 'bg-primary rounded-l',
                        style: { width: `${seenPercentage}%` },
                    },
                    {
                        value: dismissedPercentage,
                        label: 'Dismissed',
                        classes: 'bg-warning',
                        style: { width: `${dismissedPercentage}%`, left: `${seenPercentage}%` },
                    },
                    {
                        value: sentPercentage,
                        label: 'Submitted',
                        classes: 'bg-success rounded-r',
                        style: { width: `${sentPercentage}%`, left: `${seenPercentage + dismissedPercentage}%` },
                    },
                ].map(({ value, label, classes, style }) => (
                    <Tooltip
                        key={`survey-summary-chart-${label}`}
                        title={`${label} surveys: ${seenPercentage.toFixed(1)}%`}
                        delayMs={0}
                        placement="top"
                    >
                        <div className={`h-8 text-white text-center absolute cursor-pointer ${classes}`} style={style}>
                            <span className="inline-flex font-semibold leading-8">{formatPercentageValue(value)}</span>
                        </div>
                    </Tooltip>
                ))}
            </div>
            <div className="w-full flex justify-center">
                <div className="flex items-center">
                    {[
                        { label: 'Seen', color: 'bg-primary' },
                        { label: 'Dismissed', color: 'bg-warning' },
                        { label: 'Submitted', color: 'bg-success' },
                    ].map(({ label, color }) => (
                        <div key={`survey-summary-legend-${label}`} className="flex items-center mr-6">
                            <div className={`w-2 h-2 rounded-full mr-2 ${color}`} />
                            <span className="font-semibold text-muted-alt">{label}</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}

export function Summary({
    surveyUserStats,
    surveyUserStatsLoading,
}: {
    surveyUserStats: SurveyUserStats
    surveyUserStatsLoading: boolean
}): JSX.Element {
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
