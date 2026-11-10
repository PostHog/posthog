import { useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { TodayPulseEditor } from './TodayPulseEditor'
import { pulseGhosts } from './todayPulseGhosts'

const GHOST_SERIES = [
    [6, 7, 6, 8, 7, 9, 8, 10, 9, 11, 10, 12],
    [9, 8, 9, 7, 8, 8, 6, 7, 6, 7, 5, 6],
    [5, 6, 8, 7, 7, 9, 8, 8, 10, 9, 11, 11],
    [8, 8, 7, 8, 9, 8, 8, 9, 8, 9, 9, 10],
]

function ghostPoints(series: number[]): string {
    const max = Math.max(...series)
    const min = Math.min(...series)
    return series
        .map((value, index) => {
            const x = (index / (series.length - 1)) * 120
            const y = 18 - ((value - min) / (max - min || 1)) * 14
            return `${x.toFixed(1)},${y.toFixed(1)}`
        })
        .join(' ')
}

export function TodayPulseEmpty({ canPin }: { canPin: boolean }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const ghosts = pulseGhosts(currentTeam?.customer_analytics_config)

    return (
        <div className="TodayPulseEmpty" data-attr="today-pulse-empty">
            <ul className="TodayPulse TodayPulse--ghost">
                {ghosts.map((ghost, index) => (
                    <li key={ghost.key} className="TodayPulse__metric">
                        <span className="TodayPulse__name">{ghost.name}</span>
                        {ghost.configured ? (
                            <span className="TodayPulse__ghostStatus">Waiting for events</span>
                        ) : (
                            <LinkPrimitive
                                to={urls.customerAnalyticsConfiguration()}
                                className="TodayPulse__ghostStatus TodayPulse__ghostSetup"
                                data-attr="today-pulse-ghost-setup"
                            >
                                Set up
                            </LinkPrimitive>
                        )}
                        <span className="TodayPulse__spark" aria-hidden>
                            <svg viewBox="0 0 120 20" preserveAspectRatio="none" className="TodayPulse__ghostLine">
                                <polyline points={ghostPoints(GHOST_SERIES[index % GHOST_SERIES.length])} />
                            </svg>
                        </span>
                    </li>
                ))}
            </ul>
            {canPin ? (
                <Text size="xs" variant="muted" render={<p />} className="m-0 flex flex-wrap items-baseline gap-x-0.5">
                    <TodayPulseEditor
                        align="start"
                        trigger={
                            <Button variant="link" size="inline" data-attr="today-pulse-empty-pin">
                                Pin an insight
                            </Button>
                        }
                    />
                    <span>to add your own number.</span>
                </Text>
            ) : null}
        </div>
    )
}
