import clsx from 'clsx'
import React from 'react'
import { ProfilePicture } from '.'
import { Tooltip } from '../Tooltip'

export interface ProfileBubblesProps extends React.HTMLProps<HTMLDivElement> {
    people: { email: string; name?: string; title?: string }[]
    tooltip?: string
    limit?: number
}

/** Bubbles are a compact way of listing PostHog users – usually in a collaborative context, such as dashboard collaborators. */
export function ProfileBubbles({ people, tooltip, limit = 6, ...divProps }: ProfileBubblesProps): JSX.Element {
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
            <div className={clsx('ProfileBubbles', !!divProps.onClick && 'cursor-pointer')} {...divProps}>
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
