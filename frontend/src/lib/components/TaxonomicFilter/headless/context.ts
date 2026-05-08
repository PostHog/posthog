import { createContext, useContext } from 'react'

import { TaxonomicFilterApi } from '../hooks/useTaxonomicFilter'

export const TaxonomicFilterContext = createContext<TaxonomicFilterApi | null>(null)

export function useTaxonomicFilterContext(): TaxonomicFilterApi {
    const ctx = useContext(TaxonomicFilterContext)
    if (!ctx) {
        throw new Error(
            'useTaxonomicFilterContext must be used inside <TaxonomicFilter.Root>. ' +
                'Wrap your TaxonomicFilter sub-components in <TaxonomicFilter.Root>.'
        )
    }
    return ctx
}
