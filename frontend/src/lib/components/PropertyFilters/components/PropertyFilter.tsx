import React from 'react'
import { SelectGradientOverflowProps } from 'lib/components/SelectGradientOverflow'
import { TaxonomicPropertyFilter } from './TaxonomicPropertyFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export interface PropertyFilterInternalProps {
    pageKey?: string
    index: number
    selectProps: Partial<SelectGradientOverflowProps>
    onComplete: () => void
    disablePopover: boolean
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
}
export function PropertyFilter({ ...props }: PropertyFilterInternalProps): JSX.Element {
    return <TaxonomicPropertyFilter {...props} />
}
