import { ProfilePicture } from '.'
import clsx from 'clsx'

import { Tooltip } from '../Tooltip'

export interface ProfileBubblesProps extends React.HTMLProps<HTMLDivElement> {
    people: { email: string; name?: string; title?: string }[]
    tooltip?: string
    limit?: number
    className?: string
}

/** Bubbles are a compact way of listing PostHog users – usually in a collaborative context, such as dashboard collaborators. */
export function ProfileBubbles({
    people,
    tooltip,
    limit = 6,
    className,
    ...divProps
}: ProfileBubblesProps): JSX.Element {
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
        <Tooltip title={tooltip}>
            <div className={clsx('ProfileBubbles', !!divProps.onClick && 'cursor-pointer', className)} {...divProps}>
                {shownPeople.map(({ email, name, title }, index) => (
                    <ProfilePicture
                        key={email}
                        user={{
                            email,
                            first_name: name,
                        }}
                        title={title || name || email}
                        size="md"
                        index={index}
                    />
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
