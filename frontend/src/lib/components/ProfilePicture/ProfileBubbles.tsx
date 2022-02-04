import React from 'react'
import { ProfilePicture } from '.'
import { Tooltip } from '../Tooltip'

export interface ProfileBubblesProps {
    people: { email: string; name?: string; tooltip: string }[]
    limit?: number
}

export function ProfileBubbles({ people, limit = 6 }: ProfileBubblesProps): JSX.Element {
    const overflowing = people.length > limit

    let shownPeople: ProfileBubblesProps['people'] = people
    let stashedPeople: ProfileBubblesProps['people'] = []
    let restTooltips: string | undefined
    if (overflowing) {
        // The limit of bubbles is 1 less than shown because we have to account for the +n bubble.
        shownPeople = people.slice(0, limit - 1)
        stashedPeople = people.slice(limit - 1)
        restTooltips = stashedPeople.map(({ tooltip }) => tooltip).join('\n')
    }

    return (
        <div className="ProfileBubbles">
            {shownPeople.map(({ email, name, tooltip }) => (
                <Tooltip key={email} title={tooltip || name || email}>
                    <span>
                        <ProfilePicture name={name} email={email} size="md" />
                    </span>
                </Tooltip>
            ))}
            {overflowing && (
                <Tooltip title={restTooltips} overlayInnerStyle={{ whiteSpace: 'pre-wrap' }}>
                    <div className="ProfileBubbles__more">+{stashedPeople.length}</div>
                </Tooltip>
            )}
        </div>
    )
}
