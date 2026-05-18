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
 * Positioned `absolute` top-right — the parent must be `relative`.
 */
export function TaxonomicMenuToggle(): JSX.Element {
    const { useNewMenu } = useValues(taxonomicMenuPreferenceLogic)
    const { setUseNewMenu } = useActions(taxonomicMenuPreferenceLogic)

    const label = useNewMenu ? 'Switch back to the classic filter' : 'Try the new filter (beta)'

    return (
        <Tooltip title={label}>
            <button
                type="button"
                aria-label={label}
                data-attr="taxonomic-menu-toggle"
                onClick={(e) => {
                    // Don't let the click fall through to the trigger button
                    // underneath (which would open the picker).
                    e.stopPropagation()
                    setUseNewMenu(!useNewMenu)
                }}
                className="absolute -top-1.5 -right-1.5 z-10 flex size-4 items-center justify-center rounded-full border border-accent bg-surface-primary text-accent shadow-sm transition-opacity hover:opacity-70"
            >
                {useNewMenu ? <IconClockRewind className="size-3" /> : <IconFlask className="size-3" />}
            </button>
        </Tooltip>
    )
}
