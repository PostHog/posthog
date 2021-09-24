import React, { CSSProperties } from 'react'
import { useValues, BindLogic } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import 'scenes/actions/Actions.scss'
import { AnyPropertyFilter } from '~/types'
import { PathItemSelector } from './components/PathItemSelector'
import { Button } from 'antd'
import { PlusCircleOutlined } from '@ant-design/icons'

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
    const logicProps = { propertyFilters, onChange, pageKey }
    const { filters } = useValues(propertyFilterLogic(logicProps))

    return (
        <div className="mb" style={style}>
            <BindLogic logic={propertyFilterLogic} props={logicProps}>
                {filters?.length &&
                    filters.map((_, index) => {
                        return (
                            <PathItemSelector key={index} pathItem={{}} onChange={() => {}} index={index}>
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
                            </PathItemSelector>
                        )
                    })}
            </BindLogic>
        </div>
    )
}
