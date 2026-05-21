import { actions, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import type { taxonomicMenuPreferenceLogicType } from './taxonomicMenuPreferenceLogicType'

/**
 * Global, persisted preference for which taxonomic filter UI to render
 * wherever the `taxonomic-filter-menu-rebuild` flag is enabled.
 *
 * Defaults to the rebuilt menu; the toggle in `TaxonomicMenuToggle` lets a
 * user opt back to the classic filter (and forward again). One logic
 * instance, so flipping it anywhere flips every picker at once.
 */
export const taxonomicMenuPreferenceLogic = kea<taxonomicMenuPreferenceLogicType>([
    path(['lib', 'components', 'TaxonomicPopover', 'taxonomicMenuPreferenceLogic']),
    actions({
        setUseNewMenu: (useNewMenu: boolean) => ({ useNewMenu }),
    }),
    reducers({
        useNewMenu: [
            true,
            { persist: true },
            {
                setUseNewMenu: (_, { useNewMenu }) => useNewMenu,
            },
        ],
    }),
    listeners(() => ({
        setUseNewMenu: ({ useNewMenu }) => {
            posthog.capture('taxonomic filter menu preference changed', { useNewMenu })
        },
    })),
])
