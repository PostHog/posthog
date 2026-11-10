import { useValues } from 'kea'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { pulseGhosts } from './todayPulseGhosts'

export function TodayPulseEmpty(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const ghosts = pulseGhosts(currentTeam?.customer_analytics_config)

    return (
        <div className="TodayPulseEmpty" data-attr="today-pulse-empty">
            <ul className="TodayPulse TodayPulse--ghost">
                {ghosts.map((ghost) => (
                    <li key={ghost.key} className="TodayPulse__metric" data-configured={ghost.configured || undefined}>
                        <span className="TodayPulse__name">{ghost.name}</span>
                        <span className="TodayPulse__row TodayPulse__ghostRow">
                            {ghost.configured ? (
                                <>
                                    <span className="TodayPulse__value TodayPulse__ghostValue" translate="no">
                                        0
                                    </span>
                                    <span className="TodayPulse__ghostNote">No events yet</span>
                                </>
                            ) : (
                                <LinkPrimitive
                                    to={urls.customerAnalyticsConfiguration()}
                                    className="TodayPulse__ghostSetup"
                                    data-attr="today-pulse-ghost-setup"
                                >
                                    Set up
                                </LinkPrimitive>
                            )}
                        </span>
                        <span className="TodayPulse__spark" aria-hidden>
                            <svg viewBox="0 0 120 22" preserveAspectRatio="none" className="TodayPulse__ghostLine">
                                <line x1="0" y1="18" x2="120" y2="18" />
                                {ghost.configured ? <circle cx="120" cy="18" r="2.5" /> : null}
                            </svg>
                        </span>
                    </li>
                ))}
            </ul>
        </div>
    )
}
