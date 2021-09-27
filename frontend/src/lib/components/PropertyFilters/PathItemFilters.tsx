import React, { CSSProperties } from 'react'
import { useValues, BindLogic, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import 'scenes/actions/Actions.scss'
import { AnyPropertyFilter, PathType } from '~/types'
import { PathItemSelector } from './components/PathItemSelector'
import { Button, Row } from 'antd'
import { PlusCircleOutlined } from '@ant-design/icons'
import { FilterButton } from './components/PropertyFilterButton'
import { CloseButton } from '../CloseButton'

interface PropertyFiltersProps {
    endpoint?: string | null
    propertyFilters?: AnyPropertyFilter[] | null
    onChange?: null | ((filters: AnyPropertyFilter[]) => void)
    pageKey: string
    style?: CSSProperties
}

export function PathItemFilters({
    propertyFilters = null,
    onChange = null,
    pageKey,
    style = {},
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
                            <>
                                <PathItemSelector
                                    key={index}
                                    pathItem={{ type: filter.key as PathType, item: filter.value as string | null }}
                                    onChange={(pathItem) =>
                                        setFilter(
                                            index,
                                            pathItem.type || PathType.PageView,
                                            pathItem.item || null,
                                            null,
                                            'event'
                                        )
                                    }
                                    index={index}
                                >
                                    {!filter.key || !filter.value ? (
                                        <Button
                                            onClick={() => {}}
                                            className="new-prop-filter"
                                            data-attr={'new-prop-filter-' + pageKey}
                                            type="link"
                                            style={{ paddingLeft: 0 }}
                                            icon={<PlusCircleOutlined />}
                                        >
                                            Add exclusion
                                        </Button>
                                    ) : (
                                        <></>
                                    )}
                                </PathItemSelector>

                                {filter.key && filter.value && (
                                    <Row align="middle">
                                        <FilterButton>{filter.key + ' ' + filter.value}</FilterButton>
                                        {!!Object.keys(filters[index]).length && (
                                            <CloseButton
                                                onClick={() => remove(index)}
                                                style={{
                                                    cursor: 'pointer',
                                                    float: 'none',
                                                    paddingLeft: 8,
                                                    alignSelf: 'flex-start',
                                                    paddingTop: 4,
                                                }}
                                            />
                                        )}
                                    </Row>
                                )}
                            </>
                        )
                    })}
            </BindLogic>
        </div>
    )
}
