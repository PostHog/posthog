import { IconInfo } from '@posthog/icons'

import { isFlagPropertyFilter } from 'lib/components/PropertyFilters/utils'

import { AnyPropertyFilter } from '~/types'

export interface FlagDependencyEstimateCaveatProps {
    properties: AnyPropertyFilter[] | undefined
    /** Plural aggregation target name, e.g. "users" or "organizations". */
    targetName: string
}

/**
 * A flag dependency can't be expressed in the query behind the blast-radius estimate, so the count
 * and the matching-actors link both leave it out and can report a wider audience than the flag
 * targets. How much wider depends on the other flag's own rollout, which the query can't resolve.
 * Both release condition editors render this next to the estimate they qualify.
 */
export function FlagDependencyEstimateCaveat({
    properties,
    targetName,
}: FlagDependencyEstimateCaveatProps): JSX.Element | null {
    const dependencyCount = (properties ?? []).filter(isFlagPropertyFilter).length

    if (dependencyCount === 0) {
        return null
    }

    return (
        <div className="flex items-start gap-1 mt-1">
            <IconInfo className="shrink-0 mt-0.5" />
            <span>
                This estimate and the list of matching {targetName} both leave out the flag{' '}
                {dependencyCount === 1 ? 'dependency' : 'dependencies'} in this condition. Fewer {targetName} may match
                than shown.
            </span>
        </div>
    )
}
