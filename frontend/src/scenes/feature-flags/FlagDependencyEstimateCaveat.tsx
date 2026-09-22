import { IconInfo } from '@posthog/icons'

import { isFlagPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { pluralize } from 'lib/utils/strings'

import { AnyPropertyFilter } from '~/types'

export interface FlagDependencyEstimateCaveatProps {
    properties: AnyPropertyFilter[] | undefined
    /** Plural aggregation target name, e.g. "users" or "organizations". */
    targetName: string
}

/** How many flag-dependency filters a condition's properties contain. The blast-radius query can't evaluate them. */
export function countFlagDependencies(properties: AnyPropertyFilter[] | undefined): number {
    return (properties ?? []).filter(isFlagPropertyFilter).length
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
    const dependencyCount = countFlagDependencies(properties)

    if (dependencyCount === 0) {
        return null
    }

    const dependencyWord = pluralize(dependencyCount, 'dependency', 'dependencies', false)

    return (
        <div className="flex items-start gap-1 mt-1">
            <IconInfo className="shrink-0 mt-0.5" />
            <span>
                This estimate and the list of matching {targetName} both leave out the flag {dependencyWord} in this
                condition. Fewer {targetName} may match than shown.
            </span>
        </div>
    )
}
