import {
    PropertyGroupFilter,
    FilterLogicalOperator,
    PropertyGroupFilterValue,
    FilterType,
    AnyPropertyFilter,
} from '~/types'
import { Col, Row, Select } from 'antd'

interface AndOrFilterSelectProps {
    onChange: (type: FilterLogicalOperator) => void
    value: FilterLogicalOperator
    topLevelFilter?: boolean
    prefix?: React.ReactNode
    suffix?: React.ReactNode
}

export function AndOrFilterSelect({
    onChange,
    value,
    topLevelFilter,
    prefix = 'Match',
    suffix = 'filters in this group',
}: AndOrFilterSelectProps): JSX.Element {
    return (
        <Row align="middle" wrap={false} className="and-or-filter">
            <span className="ml-2">{prefix}</span>
            <Select
                optionLabelProp="label"
                dropdownClassName="and-or-filter-select"
                style={{ marginLeft: 8, marginRight: 8 }}
                value={value}
                onChange={(type) => onChange(type)}
                dropdownMatchSelectWidth={false}
                placement={topLevelFilter ? 'bottomRight' : 'bottomLeft'}
            >
                <Select.Option value={FilterLogicalOperator.And} label="all" className="condition-option">
                    <Row>
                        <div className={`condition-text ${value === FilterLogicalOperator.And ? 'selected' : ''}`}>
                            {FilterLogicalOperator.And}
                        </div>
                        <Col>
                            <div>
                                <b>All filter</b>{' '}
                            </div>
                            <div>All filters must be met (logical and)</div>
                        </Col>
                    </Row>
                </Select.Option>
                <Select.Option value={FilterLogicalOperator.Or} label="any" className="condition-option">
                    <Row>
                        <div className={`condition-text ${value === FilterLogicalOperator.Or ? 'selected' : ''}`}>
                            {FilterLogicalOperator.Or}
                        </div>
                        <Col>
                            <div>
                                <b>Any filter</b>{' '}
                            </div>
                            <div>Any filter can be met (logical or)</div>
                        </Col>
                    </Row>
                </Select.Option>
            </Select>{' '}
            {suffix}
        </Row>
    )
}
