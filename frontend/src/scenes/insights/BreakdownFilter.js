import React, { useState } from 'react'
import { Tooltip, Select, Tabs, Popover, Button } from 'antd'
import { useValues } from 'kea'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { cohortsModel } from '../../models/cohortsModel'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'
import { ShownAsValue } from 'lib/constants'
import { propertyDefinitionsLogic } from 'scenes/events/propertyDefinitionsLogic'

const { TabPane } = Tabs

function PropertyFilter({ breakdown, onChange }) {
    const { transformedPropertyDefinitions } = useValues(propertyDefinitionsLogic)
    const { personProperties } = useValues(propertyFilterLogic({ pageKey: 'breakdown' }))
    return (
        <SelectGradientOverflow
            showSearch
            autoFocus
            style={{ width: '100%' }}
            placeholder={'Break down by'}
            value={breakdown ? breakdown : undefined}
            onChange={(_, item) => onChange(item.value.replace(/event_|person_/gi, ''), item.type)}
            filterOption={(input, option) => option.value?.toLowerCase().indexOf(input.toLowerCase()) >= 0}
            data-attr="prop-breakdown-select"
        >
            {transformedPropertyDefinitions.length > 0 && (
                <Select.OptGroup key="Event properties" label="Event properties">
                    {Object.entries(transformedPropertyDefinitions).map(([key, item], index) => (
                        <Select.Option
                            key={'event_' + key}
                            value={'event_' + item.value}
                            type="event"
                            data-attr={'prop-breakdown-' + index}
                        >
                            <PropertyKeyInfo value={item.value} />
                        </Select.Option>
                    ))}
                </Select.OptGroup>
            )}
            {personProperties && (
                <Select.OptGroup key="User properties" label="User properties">
                    {Object.entries(personProperties).map(([key, item], index) => (
                        <Select.Option
                            key={'person_' + key}
                            value={'person_' + item.value}
                            type="person"
                            data-attr={'prop-filter-person-' + (transformedPropertyDefinitions.length + index)}
                        >
                            <PropertyKeyInfo value={item.value} />
                        </Select.Option>
                    ))}
                </Select.OptGroup>
            )}
        </SelectGradientOverflow>
    )
}

function CohortFilter({ breakdown, onChange }) {
    const { cohorts } = useValues(cohortsModel)
    return (
        <SelectGradientOverflow
            autoFocus
            mode="multiple"
            style={{ width: '100%' }}
            placeholder={'Break down by'}
            optionLabelProp="label"
            value={breakdown ? breakdown : undefined}
            onChange={(value) => {
                onChange(value.length > 0 ? value : null, 'cohort')
            }}
            filterOption={(input, option) =>
                option.children && option.children.toLowerCase().indexOf(input.toLowerCase()) >= 0
            }
            data-attr="cohort-breakdown-select"
        >
            <Select.Option value={'all'} type="cohort" label={'all users'} data-attr="cohort-breakdown-all-users">
                All users*
            </Select.Option>
            {cohorts &&
                cohorts.map((item, index) => {
                    return (
                        <Select.Option
                            key={item.id}
                            value={item.id}
                            type="cohort"
                            label={item.name}
                            data-attr={'cohort-breakdown-' + index}
                        >
                            {item.name}
                        </Select.Option>
                    )
                })}
        </SelectGradientOverflow>
    )
}

function Content({ breakdown, breakdown_type, onChange }) {
    return (
        <Tabs
            defaultActiveKey={breakdown_type}
            tabPosition="top"
            style={{ minWidth: 350 }}
            data-attr="breakdown-filter-content"
        >
            <TabPane tab="Property" key="property">
                <PropertyFilter
                    breakdown={(!breakdown_type || breakdown_type == 'property') && breakdown}
                    onChange={onChange}
                />
                <span className="text-muted">
                    Note: If there are more than 20 properties, <b>only the top 20</b> with the highest volume{' '}
                    <b>will be shown</b>.
                </span>
            </TabPane>
            <TabPane tab="Cohort" key="cohort">
                <CohortFilter breakdown={breakdown_type == 'cohort' && breakdown} onChange={onChange} />
            </TabPane>
        </Tabs>
    )
}

export function BreakdownFilter({ filters, onChange }) {
    const { cohorts } = useValues(cohortsModel)
    const { breakdown, breakdown_type, shown_as } = filters
    let [open, setOpen] = useState(false)
    let label = breakdown
    if (breakdown_type === 'cohort' && breakdown) {
        label = cohorts
            ? breakdown.map((cohort_id) => cohorts.filter((c) => c.id == cohort_id)[0]?.name || cohort_id).join(', ')
            : ''
    }

    return (
        <Popover
            visible={open}
            onVisibleChange={setOpen}
            content={
                <Content
                    breakdown={breakdown}
                    breakdown_type={breakdown_type}
                    key={open}
                    onChange={(value, type) => {
                        if (type !== 'cohort') {
                            setOpen(false)
                        }
                        onChange(value, type)
                    }}
                />
            }
            trigger={shown_as === ShownAsValue.STICKINESS || shown_as === ShownAsValue.LIFECYCLE ? 'none' : 'click'}
            placement="bottomLeft"
        >
            <Tooltip
                title={
                    shown_as === ShownAsValue.STICKINESS &&
                    'Break down by is not yet available in combination with Stickiness'
                }
            >
                <Button
                    shape="round"
                    type={breakdown ? 'primary' : 'default'}
                    disabled={shown_as === ShownAsValue.STICKINESS || shown_as === ShownAsValue.LIFECYCLE}
                    data-attr="add-breakdown-button"
                >
                    <PropertyKeyInfo value={label || 'Add breakdown'} />
                </Button>
            </Tooltip>
        </Popover>
    )
}
