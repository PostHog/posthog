import { useActions, useValues } from 'kea'

import { IconClockRewind, IconFlask } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip/Tooltip'

import { taxonomicMenuPreferenceLogic } from './taxonomicMenuPreferenceLogic'

/**
 * Floating corner badge rendered over every taxonomic filter trigger
 * (legacy or rebuilt) wherever the `taxonomic-filter-menu-rebuild` flag is
 * on. Flips the global `taxonomicMenuPreferenceLogic` so the user can opt
 * in/out of the rebuilt menu everywhere at once.
 *
 * Positioned `absolute` inside the trigger's top-right corner — the parent
 * must be `relative`. Kept inside the trigger box (no negative offset) so
 * an `overflow-hidden` ancestor can't clip it.
 */
export function TaxonomicMenuToggle(): JSX.Element {
    const { useNewMenu } = useValues(taxonomicMenuPreferenceLogic)
    const { setUseNewMenu } = useActions(taxonomicMenuPreferenceLogic)

    // Symmetric, state-neutral labels — the rebuilt menu is the default, so
    // framing it as "beta / try" would mislabel the primary experience.
    const label = useNewMenu ? 'Switch to the classic filter' : 'Switch to the new filter'

    return (
        <Tooltip title={label}>
            <button
                type="button"
                aria-label={label}
                data-attr="taxonomic-menu-toggle"
                onClick={(e) => {
                    // Don't let the click fall through to the trigger button
                    // underneath (which would open the picker).
                    e.preventDefault()
                    e.stopPropagation()
                    setUseNewMenu(!useNewMenu)
                }}
                className="absolute top-0 right-0 z-10 flex size-3.5 items-center justify-center rounded-full rounded-tr-sm border border-accent bg-surface-primary text-accent shadow-sm transition-opacity hover:opacity-70"
            >
                {useNewMenu ? <IconClockRewind className="size-2.5" /> : <IconFlask className="size-2.5" />}
            </button>
        </Tooltip>
    )
}
