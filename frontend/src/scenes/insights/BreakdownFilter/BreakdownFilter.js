import React, { useState } from 'react'
import { Select, Tabs, Popover, Button } from 'antd'
import { Tooltip } from 'lib/components/Tooltip'
import { useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { ViewType } from '~/types'
import { TaxonomicBreakdownFilter } from 'scenes/insights/BreakdownFilter/TaxonomicBreakdownFilter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

const { TabPane } = Tabs

function PropertyFilter({ breakdown, onChange }) {
    const { transformedPropertyDefinitions: eventProperties } = useValues(propertyDefinitionsModel)
    const { personProperties } = useValues(personPropertiesModel)

    return (
        <SelectGradientOverflow
            showSearch
            autoFocus
            delayBeforeAutoOpen={150}
            placement="bottomLeft"
            style={{ width: '100%' }}
            placeholder={'Break down by'}
            value={breakdown ? breakdown : undefined}
            onChange={(_, item) => onChange(item.value, item.type)}
            filterOption={(input, option) => option.value?.toLowerCase().indexOf(input.toLowerCase()) >= 0}
            data-attr="prop-breakdown-select"
        >
            {eventProperties.length > 0 && (
                <Select.OptGroup key="Event properties" label="Event properties">
                    {Object.entries(eventProperties).map(([key, item], index) => (
                        <Select.Option
                            key={'event_' + key}
                            value={item.value}
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
                            value={item.name}
                            type="person"
                            data-attr={'prop-filter-person-' + (eventProperties.length + index)}
                        >
                            <PropertyKeyInfo value={item.name} />
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
            delayBeforeAutoOpen={150}
            placement="bottomLeft"
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

export function OriginalBreakdownFilter({ filters, onChange }) {
    const { cohorts } = useValues(cohortsModel)
    const { breakdown, breakdown_type, insight } = filters
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
            destroyTooltipOnHide
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
            trigger={insight === ViewType.STICKINESS || insight === ViewType.LIFECYCLE ? 'none' : 'click'}
            placement="bottomLeft"
            getPopupContainer={(trigger) => trigger.parentNode} // Prevent scrolling up on trigger
        >
            <Tooltip
                title={
                    insight === ViewType.STICKINESS &&
                    'Break down by is not yet available in combination with Stickiness'
                }
            >
                <Button
                    shape="round"
                    type={breakdown ? 'primary' : 'default'}
                    disabled={insight === ViewType.STICKINESS || insight === ViewType.LIFECYCLE}
                    data-attr="add-breakdown-button"
                    style={label ? { color: '#fff' } : {}}
                >
                    <PropertyKeyInfo value={label || 'Add breakdown'} />
                </Button>
            </Tooltip>
        </Popover>
    )
}

export function BreakdownFilter(props) {
    const { featureFlags } = useValues(featureFlagLogic)
    if (featureFlags[FEATURE_FLAGS.TAXONOMIC_PROPERTY_FILTER]) {
        return <TaxonomicBreakdownFilter {...props} />
    } else {
        return <OriginalBreakdownFilter {...props} />
    }
}
