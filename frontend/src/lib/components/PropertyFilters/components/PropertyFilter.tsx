import React from 'react'
import { SelectGradientOverflowProps } from 'lib/components/SelectGradientOverflow'
import { TabbedPropertyFilter } from './TabbedPropertyFilter'
import { TaxonomicPropertyFilter } from './TaxonomicPropertyFilter'
import { UnifiedPropertyFilter } from './UnifiedPropertyFilter'

export interface PropertyFilterInternalProps {
    pageKey?: string
    index: number
    selectProps: Partial<SelectGradientOverflowProps>
    onComplete: () => void
    disablePopover: boolean
}

export interface PropertyFilterProps extends PropertyFilterInternalProps {
    variant: 'tabs' | 'taxonomic' | 'unified'
}

export function PropertyFilter({ variant = 'tabs', ...props }: PropertyFilterProps): JSX.Element {
    switch (variant) {
        case 'tabs':
            return <TabbedPropertyFilter {...props} />
        case 'taxonomic':
            return <TaxonomicPropertyFilter {...props} />
        case 'unified':
            return <UnifiedPropertyFilter {...props} />
    }
}
