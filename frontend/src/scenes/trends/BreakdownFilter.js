import React, { useState } from 'react'
import { Tooltip, Select, Tabs, Popover, Button } from 'antd'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { cohortsModel } from '../../models/cohortsModel'

const { TabPane } = Tabs

function PropertyFilter({ breakdown, onChange }) {
    const { eventProperties } = useValues(userLogic)
    return (
        <Select
            showSearch
            autoFocus
            style={{ width: '100%' }}
            placeholder={'Break down by'}
            value={breakdown ? breakdown : undefined}
            onChange={(_, { value }) => onChange(value)}
            filterOption={(input, option) =>
                option.children && option.children.toLowerCase().indexOf(input.toLowerCase()) >= 0
            }
        >
            {Object.entries(eventProperties).map(([key, item]) => {
                return (
                    <Select.Option key={key} value={item.value}>
                        {item.label}
                    </Select.Option>
                )
            })}
        </Select>
    )
}

function CohortFilter({ breakdown, onChange }) {
    const { cohorts } = useValues(cohortsModel)
    return (
        <Select
            autoFocus
            mode="multiple"
            style={{ width: '100%' }}
            placeholder={'Break down by'}
            optionLabelProp="label"
            value={breakdown ? breakdown : undefined}
            onChange={value => {
                onChange(value.length > 0 ? value : null, 'cohort')
            }}
            filterOption={(input, option) =>
                option.children && option.children.toLowerCase().indexOf(input.toLowerCase()) >= 0
            }
        >
            <Select.Option value={'all'} type="cohort" label={'all users'}>
                All users*
            </Select.Option>
            {cohorts &&
                cohorts.map(item => {
                    return (
                        <Select.Option key={item.id} value={item.id} type="cohort" label={item.name}>
                            {item.name}
                        </Select.Option>
                    )
                })}
        </Select>
    )
}

function Content({ breakdown, breakdown_type, onChange }) {
    return (
        <Tabs defaultActiveKey={breakdown_type} tabPosition="top" style={{ minWidth: 350 }}>
            <TabPane tab="Property" key="property">
                <PropertyFilter
                    breakdown={(!breakdown_type || breakdown_type == 'property') && breakdown}
                    onChange={onChange}
                />
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
            ? breakdown.map(cohort_id => cohorts.filter(c => c.id == cohort_id)[0]?.name || cohort_id).join(', ')
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
                        if (type !== 'cohort') setOpen(false)
                        onChange(value, type)
                    }}
                />
            }
            trigger="click"
            placement="bottomLeft"
        >
            <Tooltip
                title={shown_as == 'Stickiness' && 'Break down by is not yet available in combination with Stickiness'}
            >
                <Button shape="round" type={breakdown ? 'primary' : 'default'} disabled={shown_as == 'Stickiness'}>
                    {label || 'Add breakdown'}
                </Button>
            </Tooltip>
        </Popover>
    )
}
