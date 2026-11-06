import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'

import { AnyPropertyFilter } from '~/types'

import { matchingActorsUrl } from './matchingActorsUrl'

export interface MatchingActorsLinkProps {
    properties: AnyPropertyFilter[] | undefined
    resolvedGroupTypeIndex: number | null
    /** Plural aggregation target name, e.g. "users" or "organizations". */
    targetName: string
}

/**
 * Drills from a release condition's blast-radius count into the actors it matches. Both release
 * condition editors render it, so a change here lands in the plain editor and the collapsible one.
 */
export function MatchingActorsLink({
    properties,
    resolvedGroupTypeIndex,
    targetName,
}: MatchingActorsLinkProps): JSX.Element {
    return (
        <Link
            to={matchingActorsUrl(properties, resolvedGroupTypeIndex)}
            target="_blank"
            className="flex items-center gap-1 w-fit mt-1"
        >
            View matching {targetName}
            <IconOpenInNew />
        </Link>
    )
}
