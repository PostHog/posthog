import { useActions, useValues } from 'kea'

import { LemonSelect, Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

export function VerifyEventsSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <>
            <p>
                Control how PostHog handles events based on their JWT verification status. When events are sent with a
                JWT token, PostHog verifies the signature against your secret keys.
            </p>
            <p>
                <Link to="https://posthog.com/docs/api/post-only-endpoints#event-verification" target="_blank">
                    Learn more about event verification in PostHog Docs
                </Link>
            </p>

            <LemonSelect
                value={currentTeam?.verify_events || 'accept_all'}
                onChange={(value) => {
                    updateCurrentTeam({
                        verify_events: value,
                    })
                }}
                disabled={userLoading}
                options={[
                    {
                        value: 'accept_all',
                        label: 'Accept all events',
                        labelInMenu: (
                            <div>
                                <div className="font-semibold">Accept all events</div>
                                <div className="text-muted text-xs">
                                    Accept all events regardless of verification status (default)
                                </div>
                            </div>
                        ),
                    },
                    {
                        value: 'reject_invalid',
                        label: 'Reject events with invalid JWT',
                        labelInMenu: (
                            <div>
                                <div className="font-semibold">Reject events with invalid JWT</div>
                                <div className="text-muted text-xs">
                                    Reject only events that have an invalid JWT signature, accept unverified events
                                </div>
                            </div>
                        ),
                    },
                    {
                        value: 'reject_unverified',
                        label: 'Reject unverified events',
                        labelInMenu: (
                            <div>
                                <div className="font-semibold">Reject unverified events</div>
                                <div className="text-muted text-xs">
                                    Reject all events that are not verified with a valid JWT (most strict)
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
        </>
    )
}
