import React from 'react'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { LemonSwitch, LemonTag } from '@posthog/lemon-ui'

export function ActorOnEventsQuerying(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div id="actor-on-events-querying">
            <h2 className="subtitle">
                Optimized Querying{' '}
                <LemonTag type="warning" style={{ marginLeft: 8 }}>
                    Beta
                </LemonTag>
            </h2>
            <p>
                This enables optimized querying. More details regarding how these queries work can be found{' '}
                <a href="https://posthog.com/docs/how-posthog-works/queries">here</a>.
            </p>
            <LemonSwitch
                data-attr="opt-in-actor-on-events-querying"
                onChange={(checked) => {
                    updateCurrentTeam({ actor_on_events_querying_setting_enabled: checked })
                }}
                checked={!!currentTeam?.actor_on_events_querying_setting_enabled}
                label="Enable querying using optimized schemas"
                bordered
            />
        </div>
    )
}
