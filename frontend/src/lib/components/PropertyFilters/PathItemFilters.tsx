import React, { CSSProperties, useEffect } from 'react'
import { useValues, BindLogic, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import '../../../scenes/actions/Actions.scss'
import { AnyPropertyFilter } from '~/types'
import { PathItemSelector } from './components/PathItemSelector'
import { PropertyFilterButton } from './components/PropertyFilterButton'
import { SimpleOption, TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils'
import { LemonButton } from '@posthog/lemon-ui'
import { IconPlusMini } from '../icons'

interface PropertyFiltersProps {
    endpoint?: string | null
    propertyFilters?: AnyPropertyFilter[] | null
    onChange: (filters: AnyPropertyFilter[]) => void
    pageKey: string
    style?: CSSProperties
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    wildcardOptions?: SimpleOption[]
}

export function PathItemFilters({
    propertyFilters,
    onChange,
    pageKey,
    taxonomicGroupTypes,
    wildcardOptions,
}: PropertyFiltersProps): JSX.Element {
    const logicProps = { propertyFilters, onChange, pageKey }
    const { filtersWithNew } = useValues(propertyFilterLogic(logicProps))
    const { setFilter, remove, setFilters } = useActions(propertyFilterLogic(logicProps))

    useEffect(() => {
        if (propertyFilters && !objectsEqual(propertyFilters, filtersWithNew)) {
            setFilters([...propertyFilters, {}])
        }
    }, [propertyFilters])

    return (
        <BindLogic logic={propertyFilterLogic} props={logicProps}>
            {filtersWithNew?.map((filter: AnyPropertyFilter, index: number) => {
                return (
                    <div key={index} className={'mb-2'}>
                        <PathItemSelector
                            pathItem={filter.value as string | undefined}
                            onChange={(pathItem) => setFilter(index, pathItem, pathItem, null, 'event')}
                            index={index}
                            taxonomicGroupTypes={taxonomicGroupTypes}
                            wildcardOptions={wildcardOptions}
                        >
                            {!filter.value ? (
                                <LemonButton
                                    className="new-prop-filter"
                                    data-attr={'new-prop-filter-' + pageKey}
                                    type="secondary"
                                    icon={<IconPlusMini color="var(--primary)" />}
                                >
                                    Add exclusion
                                </LemonButton>
                            ) : (
                                <PropertyFilterButton
                                    item={filter}
                                    onClose={() => {
                                        remove(index)
                                    }}
                                >
                                    {filter.value as string}
                                </PropertyFilterButton>
                            )}
                        </PathItemSelector>
                    </div>
                )
            })}
        </BindLogic>
    )
}
