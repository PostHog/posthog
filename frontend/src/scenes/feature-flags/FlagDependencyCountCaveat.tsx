import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { AnyPropertyFilter } from '~/types'

import { flagDependencyWord } from './FlagDependencyEstimateCaveat'

export interface FlagDependencyCountCaveatProps {
    properties: AnyPropertyFilter[] | undefined
}

/**
 * Marks the count in a collapsed condition's header. That count leaves out flag dependencies for the same
 * reason as the estimate that `FlagDependencyEstimateCaveat` qualifies.
 */
export function FlagDependencyCountCaveat({ properties }: FlagDependencyCountCaveatProps): JSX.Element | null {
    const dependencyWord = flagDependencyWord(properties)

    if (dependencyWord === null) {
        return null
    }

    return (
        <Tooltip title={`This count leaves out the flag ${dependencyWord} in this condition.`}>
            <IconInfo className="text-muted text-xs" data-attr="flag-dependency-condition-count-caveat" />
        </Tooltip>
    )
}
