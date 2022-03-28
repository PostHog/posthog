import './SortSelect.scss'
import React from 'react'
import { LemonSelect, LemonSelectGroupOrFlatOptions } from 'lib/components/LemonSelect'
import { TaxonomicFilterLogicProps, TaxonomicSortOptionType } from 'lib/components/TaxonomicFilter/types'
import { useActions, useValues } from 'kea'
import { sortSelectLogic } from 'lib/components/TaxonomicFilter/sortSelectLogic'
import clsx from 'clsx'
import { SortAscendingIcon, SortDescendingIcon, SortIcon } from 'lib/components/icons'

function OptionLabel({ label, subLabel }: { label: string; subLabel?: string }): JSX.Element {
    return (
        <span className="taxonomic-sort-select__option">
            {label}
            {subLabel && <span className="taxonomic-sort-select__option__sublabel">({subLabel})</span>}
        </span>
    )
}

export const TAXONOMIC_SORT_OPTIONS: LemonSelectGroupOrFlatOptions = {
    ['Sort by']: {
        [TaxonomicSortOptionType.Auto]: {
            label: function RenderOption(): JSX.Element {
                return <OptionLabel label="Automatic" />
            },
            icon: <SortIcon />,
        },
        [TaxonomicSortOptionType.VerifiedAsc]: {
            label: function RenderOption(): JSX.Element {
                return <OptionLabel label="Verified" subLabel="first" />
            },
            icon: <SortAscendingIcon />,
        },
        [TaxonomicSortOptionType.VerifiedDesc]: {
            label: function RenderOption(): JSX.Element {
                return <OptionLabel label="Verified" subLabel="last" />
            },
            icon: <SortDescendingIcon />,
        },
        [TaxonomicSortOptionType.AlphabeticAsc]: {
            label: function RenderOption(): JSX.Element {
                return <OptionLabel label="Alphabetical" subLabel="A to Z" />
            },
            icon: <SortAscendingIcon />,
        },
        [TaxonomicSortOptionType.AlphabeticDesc]: {
            label: function RenderOption(): JSX.Element {
                return <OptionLabel label="Alphabetical" subLabel="Z to A" />
            },
            icon: <SortDescendingIcon />,
        },
        [TaxonomicSortOptionType.CreatedAtAsc]: {
            label: function RenderOption(): JSX.Element {
                return <OptionLabel label="Created" subLabel="new to old" />
            },
            icon: <SortAscendingIcon />,
        },
        [TaxonomicSortOptionType.CreatedAtDesc]: {
            label: function RenderOption(): JSX.Element {
                return <OptionLabel label="Created" subLabel="old to new" />
            },
            icon: <SortDescendingIcon />,
        },
        [TaxonomicSortOptionType.LastSeenAsc]: {
            label: function RenderOption(): JSX.Element {
                return <OptionLabel label="Last seen" subLabel="new to old" />
            },
            icon: <SortAscendingIcon />,
        },
        [TaxonomicSortOptionType.LastSeenDesc]: {
            label: function RenderOption(): JSX.Element {
                return <OptionLabel label="Last seen" subLabel="old to new" />
            },
            icon: <SortDescendingIcon />,
        },
        [TaxonomicSortOptionType.UpdatedAsc]: {
            label: function RenderOption(): JSX.Element {
                return <OptionLabel label="Updated" subLabel="new to old" />
            },
            icon: <SortAscendingIcon />,
        },
        [TaxonomicSortOptionType.UpdatedDesc]: {
            label: function RenderOption(): JSX.Element {
                return <OptionLabel label="Updated" subLabel="old to new" />
            },
            icon: <SortDescendingIcon />,
        },
    },
}

interface SortSelectProps {
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
}

export function SortSelect({ taxonomicFilterLogicProps }: SortSelectProps): JSX.Element {
    const logic = sortSelectLogic({ taxonomicFilterLogicKey: taxonomicFilterLogicProps.taxonomicFilterLogicKey })
    const { option, truncateControlLabel } = useValues(logic)
    const { selectOption } = useActions(logic)

    return (
        <LemonSelect
            className={clsx('taxonomic-sort-select', 'click-outside-block')}
            controlClassName={clsx(truncateControlLabel && 'hide-control-label')}
            dropdownClassName={clsx('taxonomic-sort-select__dropdown', 'click-outside-block')}
            options={TAXONOMIC_SORT_OPTIONS}
            value={option}
            onChange={(newValue) => {
                selectOption(newValue as TaxonomicSortOptionType)
            }}
            outlined
            dropdownMatchSelectWidth={false}
            showDropdownIcon={false}
            popup={{
                placement: 'bottom-end',
            }}
        />
    )
}
