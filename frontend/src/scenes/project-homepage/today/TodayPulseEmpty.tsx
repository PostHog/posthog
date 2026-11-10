import { useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { teamLogic } from 'scenes/teamLogic'

import { TodayPulseEditor } from './TodayPulseEditor'
import { pulseGhosts } from './todayPulseGhosts'

const GHOST_LINES = [
    'M0 13 C14 12 22 9 34 10 S56 12 68 8 S92 6 104 7 S116 4 120 4',
    'M0 9 C12 11 24 12 36 9 S58 5 70 7 S94 11 106 8 S116 6 120 6',
    'M0 12 C14 10 24 11 36 12 S60 8 72 9 S94 5 106 6 S116 8 120 7',
    'M0 8 C12 9 26 7 38 9 S60 12 72 10 S96 6 108 7 S116 5 120 5',
]

export function TodayPulseEmpty({ canPin }: { canPin: boolean }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const ghosts = pulseGhosts(currentTeam?.customer_analytics_config)
    const pending = ghosts.find((ghost) => ghost.configured)

    return (
        <div className="TodayPulseEmpty" data-attr="today-pulse-empty">
            <ul className="TodayPulse TodayPulse--ghost" aria-hidden>
                {ghosts.map((ghost, index) => (
                    <li key={ghost.key} className="TodayPulse__metric">
                        <span className="TodayPulse__name">{ghost.name}</span>
                        <span className="TodayPulse__row">
                            <span className="TodayPulse__ghostValue" />
                        </span>
                        <span className="TodayPulse__spark">
                            <svg viewBox="0 0 120 16" preserveAspectRatio="none" className="TodayPulse__ghostLine">
                                <path d={GHOST_LINES[index % GHOST_LINES.length]} />
                            </svg>
                        </span>
                    </li>
                ))}
            </ul>
            <Text size="xs" variant="muted" render={<p />} className="TodayPulseEmpty__note m-0">
                <span>
                    {pending
                        ? `${pending.name} fills in when events arrive.`
                        : 'Key numbers fill in when events arrive.'}
                </span>
                {canPin ? (
                    <>
                        {' '}
                        <TodayPulseEditor
                            align="start"
                            trigger={
                                <Button variant="link" size="inline" data-attr="today-pulse-empty-pin">
                                    Pin an insight
                                </Button>
                            }
                        />
                    </>
                ) : null}
            </Text>
        </div>
    )
}
