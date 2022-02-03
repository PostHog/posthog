import React from 'react'
import { Col, Input, Row, Select } from 'antd'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { CohortGroupType, MatchType } from '~/types'
import { ENTITY_MATCH_TYPE, PROPERTY_MATCH_TYPE } from 'lib/constants'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { DeleteOutlined } from '@ant-design/icons'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopup } from 'lib/components/TaxonomicPopup/TaxonomicPopup'
import { findActionName } from '~/models/actionsModel'

const { Option } = Select

export function MatchCriteriaSelector({
    onCriteriaChange,
    group,
    onRemove,
    showErrors,
}: {
    onCriteriaChange: (group: Partial<CohortGroupType>) => void
    group: CohortGroupType
    onRemove: () => void
    showErrors?: boolean
}): JSX.Element {
    const onMatchTypeChange = (input: MatchType): void => {
        onCriteriaChange({
            matchType: input,
            ...(input === ENTITY_MATCH_TYPE
                ? {
                      count_operator: 'gte',
                      days: '1',
                  }
                : {}),
        })
    }

    const errored =
        showErrors &&
        ((group.matchType === ENTITY_MATCH_TYPE && !group.properties?.length) ||
            (group.matchType === PROPERTY_MATCH_TYPE && !(group.action_id || group.event_id)))

    return (
        <div
            style={{
                padding: 15,
                border: errored ? '1px solid var(--danger)' : '1px solid rgba(0, 0, 0, 0.1)',
                borderRadius: 4,
                width: '100%',
            }}
        >
            <Row align="middle" justify="space-between">
                <div>
                    Match users who
                    <Select
                        defaultValue={PROPERTY_MATCH_TYPE}
                        value={group.matchType}
                        style={{ width: 240, marginLeft: 10 }}
                        onChange={onMatchTypeChange}
                    >
                        <Option value={PROPERTY_MATCH_TYPE}>have properties</Option>
                        <Option value={ENTITY_MATCH_TYPE}>performed action or event</Option>
                    </Select>
                </div>
                <DeleteOutlined onClick={() => onRemove()} style={{ cursor: 'pointer' }} />
            </Row>
            <Row>
                {errored && (
                    <div style={{ color: 'var(--danger)', marginTop: 16 }}>
                        {group.matchType === ENTITY_MATCH_TYPE
                            ? 'Please select an event or action.'
                            : 'Please select at least one property or remove this match group.'}
                    </div>
                )}
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
                    onChange={(properties) => {
                        onPropertyCriteriaChange({ properties })
                    }}
                    propertyFilters={group.properties}
                    style={{ margin: '1rem 0 0' }}
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.CohortsWithAllUsers,
                    ]}
                    popoverPlacement="top"
                    taxonomicPopoverPlacement="auto"
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
    const { label, days, count_operator, count } = group

    const onOperatorChange = (newCountOperator: string): void => {
        onEntityCriteriaChange({ count_operator: newCountOperator })
    }

    const onDateIntervalChange = (dateInterval: string): void => {
        onEntityCriteriaChange({ days: dateInterval })
    }

    const onEntityCountChange = (newCount: number): void => {
        onEntityCriteriaChange({ count: newCount })
    }

    const onEntityChange = (type: TaxonomicFilterGroupType, id: string | number): void => {
        if (type === TaxonomicFilterGroupType.Events && typeof id === 'string') {
            onEntityCriteriaChange({ event_id: id, action_id: undefined, label: id })
        } else if (type === TaxonomicFilterGroupType.Actions && typeof id === 'number') {
            onEntityCriteriaChange({
                action_id: id,
                event_id: undefined,
                label: findActionName(id) || `Action #${id}`,
            })
        }
    }

    return (
        <div style={{ marginTop: 16, width: '100%' }}>
            <Row gutter={8}>
                <Col flex="auto">
                    <TaxonomicPopup
                        groupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                        groupType={group.action_id ? TaxonomicFilterGroupType.Actions : TaxonomicFilterGroupType.Events}
                        value={group.action_id || group.event_id}
                        onChange={(value, groupType) => onEntityChange(groupType, value)}
                        renderValue={() => <PropertyKeyInfo value={label || 'Select an event'} disablePopover={true} />}
                        dataAttr="edit-cohort-entity-filter"
                    />
                </Col>
                <Col span={4}>
                    <OperatorSelect value={count_operator} onChange={onOperatorChange} />
                </Col>
                <Col span={3}>
                    <Input
                        required
                        value={count}
                        data-attr="entity-count"
                        onChange={(e) => onEntityCountChange(parseInt(e.target.value))}
                        placeholder="1"
                        type="number"
                    />
                </Col>
                <Col style={{ display: 'flex', alignItems: 'center' }}>times in the last</Col>
                <Col span={4}>
                    <DateIntervalSelect value={days} onChange={onDateIntervalChange} />
                </Col>
            </Row>
        </div>
    )
}

function OperatorSelect({ onChange, value }: { onChange: (operator: string) => void; value?: string }): JSX.Element {
    return (
        <Select value={value || 'gte'} style={{ width: '100%' }} onChange={onChange}>
            <Option value="gte">at least</Option>
            <Option value="eq">exactly</Option>
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
    const PRESET_OPTIONS = {
        '1': 'day',
        '7': 'week',
        '14': '2 weeks',
        '30': 'month',
    }

    const valueOrDefault = value ?? '1'

    return (
        <Select value={valueOrDefault} style={{ width: '100%' }} onChange={onChange}>
            {Object.keys(PRESET_OPTIONS).map((key) => (
                <Option value={key} key={key}>
                    {PRESET_OPTIONS[key as '1' | '7' | '14' | '30']}
                </Option>
            ))}
        </Select>
    )
}
