import { useValues } from 'kea'

import { IconPin } from '@posthog/icons'
import { Badge, Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { TodayPulseEditor } from './TodayPulseEditor'
import { pulseGhosts } from './todayPulseGhosts'

const GHOST_LINE = 'M0 14 L12 12 L24 13 L36 9 L48 11 L60 7 L72 8 L84 5 L96 6 L108 3 L120 4'

export function TodayPulseEmpty({ canPin }: { canPin: boolean }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const ghosts = pulseGhosts(currentTeam?.customer_analytics_config)
    const pending = ghosts.filter((ghost) => ghost.configured).map((ghost) => ghost.name)

    return (
        <div className="TodayPulseEmpty" data-attr="today-pulse-empty">
            <ul className="TodayPulse TodayPulse--ghost" aria-label="Key numbers that are not ready yet">
                {ghosts.map((ghost) => (
                    <li key={ghost.key} className="TodayPulse__metric">
                        <span className="TodayPulse__name">{ghost.name}</span>
                        <span className="TodayPulse__row">
                            <span className="TodayPulse__ghostValue" aria-hidden />
                            {ghost.configured ? (
                                <Badge variant="info">Pending</Badge>
                            ) : (
                                <Button
                                    size="xs"
                                    variant="link-muted"
                                    className="-ms-1"
                                    render={<LinkPrimitive to={urls.customerAnalyticsConfiguration()} />}
                                    data-attr="today-pulse-ghost-setup"
                                >
                                    Set up
                                </Button>
                            )}
                        </span>
                        <span className="TodayPulse__spark">
                            <svg
                                viewBox="0 0 120 16"
                                preserveAspectRatio="none"
                                className="TodayPulse__ghostLine"
                                aria-hidden
                            >
                                <path d={GHOST_LINE} />
                            </svg>
                        </span>
                    </li>
                ))}
            </ul>
            <div className="TodayPulseEmpty__footer">
                <Text size="xs" variant="muted" render={<p />} className="m-0">
                    {pending.length === 0
                        ? 'Pin the trend insights you check every day. PostHog also adds the ones your team opens most.'
                        : pending.length === 1
                          ? `${pending[0]} is set up for you and fills in when events arrive. Pin a trend insight to add your own.`
                          : `${pending.join(' and ')} are set up for you and fill in when events arrive. Pin a trend insight to add your own.`}
                </Text>
                {canPin ? (
                    <TodayPulseEditor
                        align="start"
                        trigger={
                            <Button size="sm" variant="outline" data-attr="today-pulse-empty-pin">
                                <IconPin />
                                Pin a number
                            </Button>
                        }
                    />
                ) : null}
            </div>
        </div>
    )
}
