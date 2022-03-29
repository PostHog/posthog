import './SortSelect.scss'
import React from 'react'
import { LemonSelect } from 'lib/components/LemonSelect'
import { TaxonomicFilterLogicProps, TaxonomicSortOptionType } from 'lib/components/TaxonomicFilter/types'
import { useActions, useValues } from 'kea'
import { sortSelectLogic } from 'lib/components/TaxonomicFilter/sortSelectLogic'
import clsx from 'clsx'

interface SortSelectProps {
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
}

export function SortSelect({ taxonomicFilterLogicProps }: SortSelectProps): JSX.Element {
    console.log('PROPS', taxonomicFilterLogicProps)
    const logic = sortSelectLogic(taxonomicFilterLogicProps)
    const { option, truncateControlLabel, defaultOptions } = useValues(logic)
    const { selectOption } = useActions(logic)
    console.log('GROUP', defaultOptions)

    return (
        <LemonSelect
            className={clsx('taxonomic-sort-select', 'click-outside-block')}
            controlClassName={clsx(truncateControlLabel && 'hide-control-label')}
            dropdownClassName={clsx('taxonomic-sort-select__dropdown', 'click-outside-block')}
            options={defaultOptions}
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
