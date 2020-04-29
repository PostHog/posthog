import React, { Component, useState } from 'react'
import { selectStyle } from '../../lib/utils'
import { Select, Tabs } from 'antd'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { cohortsModel } from '../../models/cohortsModel'

const { TabPane } = Tabs

function PropertyFilter({ breakdown, onChange }) {
    const { eventProperties } = useValues(userLogic)
    const { search } = useState()
    return (
        <Select
            showSearch
            style={{ width: '80%', maxWidth: 200 }}
            placeholder={'Break down by'}
            value={breakdown ? breakdown : undefined}
            onChange={(_, { value }) => onChange(value)}
            styles={selectStyle}
            filterOption={(input, option) => option.children.toLowerCase().indexOf(input.toLowerCase()) >= 0}
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
    const { cohorts, cohortsLoading } = useValues(cohortsModel)
    return (
        <Select
            // showSearch
            mode="multiple"
            style={{ width: '80%', maxWidth: 200 }}
            placeholder={'Break down by'}
            optionLabelProp="label"
            value={breakdown ? breakdown : undefined}
            onChange={value => {
                onChange(value, 'cohort')
            }}
            styles={selectStyle}
            filterOption={(input, option) => option.children.toLowerCase().indexOf(input.toLowerCase()) >= 0}
        >
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

export function BreakdownFilter({ breakdown, breakdown_type, onChange }) {
    return (
        <Tabs defaultActiveKey={breakdown_type}>
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
