import React from 'react'
import { ProfilePicture } from '.'
import { Tooltip } from '../Tooltip'

export interface ProfileBubblesProps {
    people: { email: string; name?: string; title?: string }[]
    tooltip?: string
    limit?: number
}

export function ProfileBubbles({ people, tooltip, limit = 6 }: ProfileBubblesProps): JSX.Element {
    const overflowing = people.length > limit

    let shownPeople: ProfileBubblesProps['people'] = people
    let stashedPeople: ProfileBubblesProps['people'] = []
    let restTitle: string | undefined
    if (overflowing) {
        // The limit of bubbles is 1 less than shown because we have to account for the +n bubble.
        shownPeople = people.slice(0, limit - 1)
        stashedPeople = people.slice(limit - 1)
        restTitle = stashedPeople.map(({ email, name, title }) => title || name || email).join(', ')
    }

    return (
        <Tooltip title={tooltip} overlayStyle={{ maxWidth: 'none' }}>
            <div className="ProfileBubbles">
                {shownPeople.map(({ email, name, title }) => (
                    <ProfilePicture key={email} name={name} email={email} title={title || name || email} size="md" />
                ))}
                {overflowing && (
                    <div className="ProfileBubbles__more" title={restTitle}>
                        +{stashedPeople.length}
                    </div>
                )}
            </div>
        </Tooltip>
    )
}
