import React, { CSSProperties, useEffect } from 'react'
import { useValues, BindLogic, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import '../../../scenes/actions/Actions.scss'
import { AnyPropertyFilter } from '~/types'
import { PathItemSelector } from './components/PathItemSelector'
import { Button, Row } from 'antd'
import { PlusCircleOutlined } from '@ant-design/icons'
import { PropertyFilterButton } from './components/PropertyFilterButton'
import { CloseButton } from '../CloseButton'
import { SimpleOption, TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils'

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
    style = {},
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
        <div className="mb" style={style}>
            <BindLogic logic={propertyFilterLogic} props={logicProps}>
                {filtersWithNew?.length &&
                    filtersWithNew.map((filter: AnyPropertyFilter, index: number) => {
                        return (
                            <div key={index} style={{ margin: '0.25rem 0', padding: '0.25rem 0' }}>
                                <PathItemSelector
                                    pathItem={filter.value as string | undefined}
                                    onChange={(pathItem) => setFilter(index, pathItem, pathItem, null, 'event')}
                                    index={index}
                                    taxonomicGroupTypes={taxonomicGroupTypes}
                                    wildcardOptions={wildcardOptions}
                                >
                                    {!filter.value ? (
                                        <Button
                                            className="new-prop-filter"
                                            data-attr={'new-prop-filter-' + pageKey}
                                            type="link"
                                            style={{ paddingLeft: 0 }}
                                            icon={<PlusCircleOutlined />}
                                        >
                                            Add exclusion
                                        </Button>
                                    ) : (
                                        <Row align="middle">
                                            <PropertyFilterButton item={filter}>
                                                {filter.value as string}
                                            </PropertyFilterButton>
                                            {!!Object.keys(filtersWithNew[index]).length && (
                                                <CloseButton
                                                    onClick={(e: Event) => {
                                                        remove(index)
                                                        e.stopPropagation()
                                                    }}
                                                    style={{
                                                        cursor: 'pointer',
                                                        float: 'none',
                                                        paddingLeft: 8,
                                                        alignSelf: 'center',
                                                    }}
                                                />
                                            )}
                                        </Row>
                                    )}
                                </PathItemSelector>
                            </div>
                        )
                    })}
            </BindLogic>
        </div>
    )
}
