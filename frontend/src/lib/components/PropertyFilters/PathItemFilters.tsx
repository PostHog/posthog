import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { SimpleOption, TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { PathItemSelector } from './components/PathItemSelector'
import { PropertyFilterButton } from './components/PropertyFilterButton'
import { propertyFilterLogic } from './propertyFilterLogic'

interface PropertyFiltersProps {
    endpoint?: string | null
    propertyFilters?: AnyPropertyFilter[] | null
    onChange: (filters: AnyPropertyFilter[]) => void
    pageKey: string
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
    const { filtersWithNew, filterIdsWithNew } = useValues(propertyFilterLogic(logicProps))
    const { setFilter, remove, setFilters } = useActions(propertyFilterLogic(logicProps))

    useEffect(() => {
        setFilters(propertyFilters ?? [])
    }, [propertyFilters, setFilters])

    return (
        <BindLogic logic={propertyFilterLogic} props={logicProps}>
            {filtersWithNew?.map((filter: AnyPropertyFilter, index: number) => {
                return (
                    <div key={filterIdsWithNew[index]} className="mb-2">
                        <PathItemSelector
                            pathItem={filter.value as string | undefined}
                            onChange={(pathItem) =>
                                setFilter(index, {
                                    key: pathItem,
                                    value: pathItem,
                                    type: PropertyFilterType.Event,
                                    operator: PropertyOperator.Exact,
                                })
                            }
                            index={index}
                            taxonomicGroupTypes={taxonomicGroupTypes}
                            wildcardOptions={wildcardOptions}
                        >
                            {!filter.value ? (
                                <LemonButton
                                    className="new-prop-filter"
                                    data-attr={'new-prop-filter-' + pageKey}
                                    type="secondary"
                                    icon={<IconPlusSmall />}
                                    sideIcon={null}
                                >
                                    Add exclusion
                                </LemonButton>
                            ) : (
                                <PropertyFilterButton item={filter} onClose={() => remove(index)}>
                                    {filter.value.toString()}
                                </PropertyFilterButton>
                            )}
                        </PathItemSelector>
                    </div>
                )
            })}
        </BindLogic>
    )
}
