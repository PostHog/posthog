import React, { useState } from 'react'
import { Select, Row, Button, Input } from 'antd'
import { CohortEntityFilterBox } from './CohortEntityFilterBox'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SelectDownIcon } from 'lib/components/SelectDownIcon'

const { Option } = Select

const ENTITY_MATCH_TYPE = 'entities'
const PROPERTY_MATCH_TYPE = 'properties'

export function MatchCriteriaSelector({}: { onChange: (criteriaType: string) => void }): JSX.Element {
    const [matchType, setMatchType] = useState('properties')

    const onMatchTypeChange = (input: string): void => {
        setMatchType(input)
    }

    return (
        <div style={{ padding: 10, border: '1px solid rgba(0, 0, 0, 0.3)', borderRadius: 4 }}>
            <Row align="middle">
                Match users who have
                <Select
                    defaultValue={PROPERTY_MATCH_TYPE}
                    value={matchType}
                    style={{ width: 240 }}
                    onChange={onMatchTypeChange}
                >
                    <Option value={PROPERTY_MATCH_TYPE}>properties</Option>
                    <Option value={ENTITY_MATCH_TYPE}>performed action or event</Option>
                </Select>
            </Row>
            <Row align="middle">
                {matchType === ENTITY_MATCH_TYPE ? <EntityCriteriaRow /> : <PropertyCriteriaRow />}
            </Row>
        </div>
    )
}

export function PropertyCriteriaRow(): JSX.Element {
    return (
        <div
            style={{
                display: 'flex',
                flexDirection: 'row',
                justifyContent: 'space-between',
                alignItems: 'center',
                width: '100%',
            }}
         />
    )
}

export function EntityCriteriaRow(): JSX.Element {
    const [open, setOpen] = useState(false)
    const [count, setCount] = useState(1)

    return (
        <div
            style={{
                display: 'flex',
                flexDirection: 'row',
                justifyContent: 'space-between',
                alignItems: 'center',
                width: '100%',
            }}
        >
            <div style={{ flex: 3, marginRight: 5 }}>
                <Button
                    onClick={() => setOpen(!open)}
                    className="full-width"
                    style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                    }}
                    data-attr="edit-cohort-entity-filter"
                >
                    <PropertyKeyInfo value={''} />
                    <SelectDownIcon className="text-muted" />
                </Button>
                <CohortEntityFilterBox open={open} />
            </div>
            <div style={{ flex: 2, marginLeft: 5, marginRight: 5 }}>
                <OperatorSelect onChange={() => {}} />
            </div>
            <div style={{ flex: 1, marginLeft: 5, marginRight: 5 }}>
                <Input required value={count} data-attr="entity-count" onChange={(e) => setCount(e.target.value)} />
            </div>
            <div style={{ flex: 2, marginLeft: 2, marginRight: 2, textAlign: 'center' }}>times in the last</div>
            <div style={{ flex: 2, marginLeft: 5 }}>
                <DateRangeSelect onChange={() => {}} />
            </div>
        </div>
    )
}

function OperatorSelect({ onChange }: { onChange: (operator: string) => void }): JSX.Element {
    return (
        <Select defaultValue="eq" style={{ width: '100%' }} onChange={onChange}>
            <Option value="eq">exactly</Option>
            <Option value="lte">at least</Option>
            <Option value="gte">at most</Option>
        </Select>
    )
}

function DateRangeSelect({ onChange }: { onChange: (operator: string) => void }): JSX.Element {
    return (
        <Select defaultValue="1d" style={{ width: '100%' }} onChange={onChange}>
            <Option value="1d">day</Option>
            <Option value="7d">week</Option>
            <Option value="14d">2 weeks</Option>
            <Option value="30d">month</Option>
        </Select>
    )
}
