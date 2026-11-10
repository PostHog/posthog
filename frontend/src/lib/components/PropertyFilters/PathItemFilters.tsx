import { BindLogic, useActions, useValues } from 'kea'

import { IconPlus, IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator, PropertyFilterRow } from '~/types'

import { SimpleOption, TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { PathItemSelector } from './components/PathItemSelector'
import { PropertyFilterButton } from './components/PropertyFilterButton'
import { propertyFilterLogic } from './propertyFilterLogic'
import { isPropertyGroupFilterLike } from './utils'

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
    const { setFilter, remove } = useActions(propertyFilterLogic(logicProps))
    const quillSurface = useQuillSurface()

    return (
        <BindLogic logic={propertyFilterLogic} props={logicProps}>
            {filtersWithNew?.map((row: PropertyFilterRow, index: number) => {
                // Path filters are always leaf rows, so a nested group never reaches this editor.
                const filter = isPropertyGroupFilterLike(row) ? null : row
                return (
                    <div key={filterIdsWithNew[index]} className="mb-2">
                        <PathItemSelector
                            pathItem={filter?.value as string | undefined}
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
                            {!filter?.value && quillSurface ? (
                                <Button
                                    variant="outline"
                                    className="new-prop-filter"
                                    data-attr={'new-prop-filter-' + pageKey}
                                >
                                    <IconPlus />
                                    Add exclusion
                                </Button>
                            ) : !filter?.value ? (
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
