import React from 'react'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonSelectOptionData } from 'lib/components/LemonSelect/LemonSelect'
import { SortAscendingIcon, SortDescendingIcon, SortIcon } from 'lib/components/icons'

export function renderOptionLabel(label: string, subLabel?: string): JSX.Element {
    return (
        <span className="taxonomic-sort-select__option">
            {label}
            {subLabel && <span className="taxonomic-sort-select__option__sublabel">({subLabel})</span>}
        </span>
    )
}

export function renderOptionIcon(order: TaxonomicSortDirection): JSX.Element {
    if (order === TaxonomicSortDirection.Ascending) {
        return <SortAscendingIcon />
    }
    if (order === TaxonomicSortDirection.Descending) {
        return <SortDescendingIcon />
    }
    return <SortIcon />
}

export const TAXONOMIC_SORT_ALLOWLIST = [
    TaxonomicFilterGroupType.Events,
    TaxonomicFilterGroupType.CustomEvents,
    TaxonomicFilterGroupType.Actions,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.NumericalEventProperties,
]
export const TAXONOMIC_COHORTS_SORT_ALLOWLIST = [
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.CohortsWithAllUsers,
]

export enum TaxonomicSortDirection {
    Ascending = 'ascending',
    Descending = 'descending',
    None = 'none',
}

export interface TaxonomicOption extends LemonSelectOptionData {
    available?: TaxonomicFilterGroupType[]
    order?: TaxonomicSortDirection
}
