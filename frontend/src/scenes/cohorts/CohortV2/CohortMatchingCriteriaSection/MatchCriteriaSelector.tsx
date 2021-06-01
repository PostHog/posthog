import React, { useState } from 'react'
import { Select, Row, Button, Input } from 'antd'
import { CohortEntityFilterBox } from './CohortEntityFilterBox'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SelectDownIcon } from 'lib/components/SelectDownIcon'
import { CohortGroupType, PropertyFilter, MatchType } from '~/types'
import { ACTION_TYPE, EVENT_TYPE, ENTITY_MATCH_TYPE, PROPERTY_MATCH_TYPE } from 'lib/constants'
import { CloseButton } from 'lib/components/CloseButton'
import { PropertyFilters } from 'lib/components/PropertyFilters'

const { Option } = Select

export function MatchCriteriaSelector({
    onCriteriaChange,
    group,
    onRemove,
}: {
    onCriteriaChange: (group: Partial<CohortGroupType>) => void
    group: CohortGroupType
    onRemove: () => void
}): JSX.Element {
    const onMatchTypeChange = (input: MatchType): void => {
        onCriteriaChange({
            matchType: input,
        })
    }

    return (
        <div style={{ padding: 15, border: '1px solid rgba(0, 0, 0, 0.1)', borderRadius: 4 }}>
            <Row align="middle" justify="space-between">
                <div>
                    Match users who have
                    <Select
                        defaultValue={PROPERTY_MATCH_TYPE}
                        value={group.matchType}
                        style={{ width: 240, marginLeft: 10 }}
                        onChange={onMatchTypeChange}
                    >
                        <Option value={PROPERTY_MATCH_TYPE}>properties</Option>
                        <Option value={ENTITY_MATCH_TYPE}>performed action or event</Option>
                    </Select>
                </div>
                <CloseButton onClick={() => onRemove()} style={{ cursor: 'pointer', float: 'none', paddingLeft: 8 }} />
            </Row>
            <Row align="middle">
                {group.matchType === ENTITY_MATCH_TYPE ? (
                    <EntityCriteriaRow group={group} onEntityCriteriaChange={onCriteriaChange} />
                ) : (
                    <PropertyCriteriaRow onPropertyCriteriaChange={onCriteriaChange} group={group} />
                )}
            </Row>
        </div>
    )
}

function PropertyCriteriaRow({
    group,
    onPropertyCriteriaChange,
}: {
    onPropertyCriteriaChange: (group: Partial<CohortGroupType>) => void
    group: CohortGroupType
}): JSX.Element {
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
                <PropertyFilters
                    endpoint="person"
                    pageKey={group.id}
                    onChange={(properties: PropertyFilter[]) => {
                        onPropertyCriteriaChange({ properties })
                    }}
                    propertyFilters={group.properties || {}}
                    style={{ margin: '1rem 0 0' }}
                    popoverPlacement="bottomRight"
                />
            </div>
        </div>
    )
}

function EntityCriteriaRow({
    onEntityCriteriaChange,
    group,
}: {
    onEntityCriteriaChange: (group: Partial<CohortGroupType>) => void
    group: CohortGroupType
}): JSX.Element {
    const [open, setOpen] = useState(false)

    const { label, days, operator, count } = group

    const onOperatorChange = (operator: string): void => {
        onEntityCriteriaChange({ operator })
    }

    const onDateIntervalChange = (dateInterval: string): void => {
        onEntityCriteriaChange({ days: dateInterval })
    }

    const onEntityCountChange = (count: number): void => {
        onEntityCriteriaChange({ count })
    }

    const onEntityChange = (type: any, id: string | number, label: string): void => {
        if (type === EVENT_TYPE && typeof id === 'string') {
            onEntityCriteriaChange({ event_id: id, label })
        } else if (type === ACTION_TYPE && typeof id === 'number') {
            onEntityCriteriaChange({ action_id: id, label })
        }
        setOpen(false)
    }

    return (
        <div
            style={{
                display: 'flex',
                flexDirection: 'row',
                justifyContent: 'space-between',
                alignItems: 'center',
                width: '100%',
                marginTop: 10,
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
                    <PropertyKeyInfo value={label || ''} />
                    <SelectDownIcon className="text-muted" />
                </Button>
                <CohortEntityFilterBox open={open} onSelect={onEntityChange} />
            </div>
            <div style={{ flex: 2, marginLeft: 5, marginRight: 5 }}>
                <OperatorSelect value={operator} onChange={onOperatorChange} />
            </div>
            <div style={{ flex: 1, marginLeft: 5, marginRight: 5 }}>
                <Input
                    required
                    value={count}
                    data-attr="entity-count"
                    onChange={(e) => onEntityCountChange(e.target.value)}
                />
            </div>
            <div style={{ flex: 2, marginLeft: 2, marginRight: 2, textAlign: 'center' }}>times in the last</div>
            <div style={{ flex: 2, marginLeft: 5 }}>
                <DateIntervalSelect value={days} onChange={onDateIntervalChange} />
            </div>
        </div>
    )
}

function OperatorSelect({ onChange, value }: { onChange: (operator: string) => void; value?: string }): JSX.Element {
    return (
        <Select value={value || 'eq'} style={{ width: '100%' }} onChange={onChange}>
            <Option value="eq">exactly</Option>
            <Option value="gte">at least</Option>
            <Option value="lte">at most</Option>
        </Select>
    )
}

function DateIntervalSelect({
    onChange,
    value,
}: {
    onChange: (dateInterval: string) => void
    value?: string
}): JSX.Element {
    return (
        <Select value={value || '1d'} style={{ width: '100%' }} onChange={onChange}>
            <Option value="1d">day</Option>
            <Option value="7d">week</Option>
            <Option value="14d">2 weeks</Option>
            <Option value="30d">month</Option>
        </Select>
    )
}
