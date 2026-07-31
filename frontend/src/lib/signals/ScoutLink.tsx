import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { scoutDisplayName } from './signalCardSourceLine'

/**
 * The authoring scout's prettified name, linked to its detail page in the inbox so a reader can jump
 * straight from a report or finding to the scout that wrote it. Renders nothing when the slug can't be
 * prettified (a bare/empty `signals-scout` slug). `stopPropagation` keeps a click from also triggering
 * an enclosing card/row link.
 */
export function ScoutLink({ skillName, className }: { skillName: string; className?: string }): JSX.Element | null {
    const name = scoutDisplayName(skillName)
    if (!name) {
        return null
    }
    return (
        <Link to={urls.inboxScout(skillName)} className={className} onClick={(e) => e.stopPropagation()}>
            {name}
        </Link>
    )
}
