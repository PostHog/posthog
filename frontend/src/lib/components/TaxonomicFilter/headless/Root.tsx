import { ReactNode } from 'react'

import { useTaxonomicFilter, UseTaxonomicFilterOptions } from '../hooks/useTaxonomicFilter'
import { TaxonomicFilterContext } from './context'

export interface TaxonomicFilterRootProps extends UseTaxonomicFilterOptions {
    children: ReactNode
    className?: string
    /** Spread `rootProps` (incl. onKeyDown) onto this wrapper. Default true. */
    bindRootProps?: boolean
}

export function TaxonomicFilterRoot({
    children,
    className,
    bindRootProps = true,
    ...opts
}: TaxonomicFilterRootProps): JSX.Element {
    const api = useTaxonomicFilter(opts)
    return (
        <TaxonomicFilterContext.Provider value={api} data-quill>
            <div className={className} {...(bindRootProps ? api.rootProps : {})}>
                {children}
            </div>
        </TaxonomicFilterContext.Provider>
    )
}
