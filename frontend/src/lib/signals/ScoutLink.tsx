import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { scoutNameFromSlug } from './signalCardSourceLine'

/**
 * The authoring scout's name, linked to its detail page in the inbox so a reader can jump straight from a
 * report or finding to the scout that wrote it. Pass `name` when the caller can resolve the team's display
 * name; otherwise the slug is prettified. Renders nothing for a bare/empty `signals-scout` slug.
 * `stopPropagation` keeps a click from also triggering an enclosing card/row link.
 */
export function ScoutLink({
    skillName,
    name,
    className,
}: {
    skillName: string
    name?: string | null
    className?: string
}): JSX.Element | null {
    const label = name || scoutNameFromSlug(skillName)
    if (!label) {
        return null
    }
    return (
        <Link to={urls.inboxScout(skillName)} className={className} onClick={(e) => e.stopPropagation()}>
            {label}
        </Link>
    )
}
