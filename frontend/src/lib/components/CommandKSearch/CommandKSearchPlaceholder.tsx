import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { cn } from '@posthog/quill'

import { FILTER_DEFINITIONS } from './commandKQuery'
import { commandKSearchLogic } from './commandKSearchLogic'

const DEFINITION_EXAMPLES = FILTER_DEFINITIONS.flatMap((definition) =>
    definition.example ? [`${definition.key}:${definition.example}`] : []
)
// Every other filter comes first, then the first one negated, then each `is:` type.
const FILTER_EXAMPLES = [...DEFINITION_EXAMPLES, `-${DEFINITION_EXAMPLES[0]}`]

/** The empty input's hint, which cycles an example through every filter and every `is:` type. */
export function CommandKSearchPlaceholder(): JSX.Element {
    const { filterOptions } = useValues(commandKSearchLogic)
    const examples = useMemo(
        () => [...FILTER_EXAMPLES, ...filterOptions.is.map((option) => `is:${option.typedValue ?? option.value}`)],
        [filterOptions.is]
    )
    // Counts every cycle, so only the very first example skips its fade-in, not each return to it.
    const [cycle, setCycle] = useState(0)

    return (
        <>
            <span>Search or ask PostHog AI… try&nbsp;</span>
            {/* Each cycle remounts the example, and its animation's end moves to the next one. Reduced motion keeps the first. */}
            <span
                key={cycle}
                translate="no"
                className={cn('quill-fade-cycle', cycle === 0 && 'quill-fade-cycle--settled')}
                onAnimationEnd={() => setCycle((current) => current + 1)}
            >
                {examples[cycle % examples.length]}
            </span>
        </>
    )
}
