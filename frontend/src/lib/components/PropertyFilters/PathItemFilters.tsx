import React, { CSSProperties } from 'react'
import { useValues, BindLogic, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import 'scenes/actions/Actions.scss'
import { AnyPropertyFilter } from '~/types'
import { PathItemSelector } from './components/PathItemSelector'
import { Button, Row } from 'antd'
import { PlusCircleOutlined } from '@ant-design/icons'
import { FilterButton } from './components/PropertyFilterButton'
import { CloseButton } from '../CloseButton'
import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'

interface PropertyFiltersProps {
    endpoint?: string | null
    propertyFilters?: AnyPropertyFilter[] | null
    onChange?: null | ((filters: AnyPropertyFilter[]) => void)
    pageKey: string
    style?: CSSProperties
    groupTypes?: TaxonomicFilterGroupType[]
}

export function PathItemFilters({
    propertyFilters = null,
    onChange = null,
    pageKey,
    style = {},
    groupTypes,
}: PropertyFiltersProps): JSX.Element {
    const logicProps = { propertyFilters, onChange, pageKey, urlOverride: 'exclude_events' }
    const { filters } = useValues(propertyFilterLogic(logicProps))
    const { setFilter, remove } = useActions(propertyFilterLogic(logicProps))

    return (
        <div className="mb" style={style}>
            <BindLogic logic={propertyFilterLogic} props={logicProps}>
                {filters?.length &&
                    filters.map((filter, index) => {
                        return (
                            <div key={index} style={{ margin: '0.25rem 0', padding: '0.25rem 0' }}>
                                <PathItemSelector
                                    pathItem={filter.value as string | undefined}
                                    onChange={(pathItem) => setFilter(index, pathItem, pathItem, null, 'event')}
                                    index={index}
                                    groupTypes={groupTypes}
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
                                            <FilterButton>{filter.value as string}</FilterButton>
                                            {!!Object.keys(filters[index]).length && (
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
