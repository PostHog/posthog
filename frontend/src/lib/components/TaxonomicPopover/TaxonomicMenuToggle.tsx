import { useActions, useValues } from 'kea'

import { IconClockRewind, IconFlask } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { taxonomicMenuPreferenceLogic } from './taxonomicMenuPreferenceLogic'

/**
 * Small, deliberately visible toggle rendered next to every taxonomic
 * filter trigger (legacy or rebuilt) wherever the
 * `taxonomic-filter-menu-rebuild` flag is on. Flips the global
 * `taxonomicMenuPreferenceLogic` so the user can opt in/out of the new
 * menu everywhere at once.
 */
export function TaxonomicMenuToggle(): JSX.Element {
    const { useNewMenu } = useValues(taxonomicMenuPreferenceLogic)
    const { setUseNewMenu } = useActions(taxonomicMenuPreferenceLogic)

    return (
        <LemonButton
            size="small"
            type="secondary"
            icon={useNewMenu ? <IconClockRewind /> : <IconFlask className="text-accent" />}
            tooltip={useNewMenu ? 'Switch back to the classic filter' : 'Try the new filter (beta)'}
            aria-label={useNewMenu ? 'Switch back to the classic filter' : 'Try the new filter'}
            data-attr="taxonomic-menu-toggle"
            onClick={() => setUseNewMenu(!useNewMenu)}
        />
    )
}
