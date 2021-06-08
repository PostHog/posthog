/*
Contains the property filter component where filtering by properties or cohorts are separated in tabs.
*/
import React, { useState } from 'react'
import { Col, Row, Select, Tabs } from 'antd'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { cohortsModel } from '~/models/cohortsModel'
import { useValues, useActions } from 'kea'
import { SelectGradientOverflow, SelectGradientOverflowProps } from 'lib/components/SelectGradientOverflow'
import { Link } from '../../Link'
import { PropertySelect } from './PropertySelect'
import { OperatorValueSelect } from './OperatorValueSelect'
import { isOperatorMulti, isOperatorRegex } from 'lib/utils'
import { PropertyOptionGroup } from './PropertySelect'
import { PropertyOperator } from '~/types'
import { PropertyFilterInternalProps } from './PropertyFilter'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

const { TabPane } = Tabs

interface PropertyPaneProps {
    onComplete: CallableFunction
    setThisFilter: CallableFunction // TODO type this
    propkey: string
    value: string
    operator: PropertyOperator
    type: string
    displayOperatorAndValue?: boolean
    selectProps: Partial<SelectGradientOverflowProps>
}

function PropertyPaneContents({
    onComplete,
    setThisFilter,
    propkey,
    value,
    operator,
    type,
    displayOperatorAndValue,
    selectProps: { delayBeforeAutoOpen = 0 },
}: PropertyPaneProps): JSX.Element {
    const { personProperties } = useValues(personPropertiesModel)
    const { transformedPropertyDefinitions: eventProperties } = useValues(propertyDefinitionsModel)

    const optionGroups: PropertyOptionGroup[] = [
        {
            type: 'event',
            label: 'Event properties',
            options: eventProperties,
        },
        {
            type: 'person',
            label: 'User properties',
            options: personProperties.map((property) => ({
                label: property.name,
                value: property.name,
            })),
        },
    ]

    if (eventProperties.length > 0) {
        optionGroups.push({
            type: 'element',
            label: 'Elements',
            options: ['tag_name', 'text', 'href', 'selector'].map((option) => ({
                value: option,
                label: option,
            })),
        })
    }

    return (
        <Row gutter={8} className="full-width" wrap={false}>
            <Col flex={1} style={{ minWidth: '11rem' }}>
                <PropertySelect
                    value={
                        type === 'cohort'
                            ? null
                            : {
                                  value: propkey,
                                  label:
                                      keyMapping[type === 'element' ? 'element' : 'event'][propkey]?.label || propkey,
                              }
                    }
                    onChange={(newType, newValue) =>
                        setThisFilter(
                            newValue,
                            undefined,
                            newValue === '$active_feature_flags' ? 'icontains' : operator,
                            newType
                        )
                    }
                    optionGroups={optionGroups}
                    autoOpenIfEmpty
                    delayBeforeAutoOpen={delayBeforeAutoOpen}
                    placeholder="Property key"
                />
            </Col>

            {displayOperatorAndValue && (
                <OperatorValueSelect
                    type={type}
                    propkey={propkey}
                    operator={operator}
                    value={value}
                    onChange={(newOperator, newValue) => {
                        setThisFilter(propkey, newValue, newOperator, type)
                        if (
                            newOperator &&
                            newValue &&
                            !(isOperatorMulti(newOperator) || isOperatorRegex(newOperator))
                        ) {
                            onComplete()
                        }
                    }}
                    columnOptions={{
                        flex: 1,
                        style: {
                            maxWidth: '50vw',
                        },
                    }}
                />
            )}
        </Row>
    )
}

interface CohortPaneProps {
    onComplete: CallableFunction
    setThisFilter: CallableFunction // TODO: type this
    value: string
    displayOperatorAndValue?: boolean
    selectProps?: SelectGradientOverflowProps
}

function CohortPaneContents({
    onComplete,
    setThisFilter,
    value,
    displayOperatorAndValue,
    selectProps,
}: CohortPaneProps): JSX.Element {
    const { cohorts } = useValues(cohortsModel)

    return (
        <Row gutter={8} className="full-width" wrap={false}>
            <Col flex={1} style={{ minWidth: '11rem' }}>
                <SelectGradientOverflow
                    style={{ width: '100%' }}
                    showSearch
                    optionFilterProp="children"
                    labelInValue
                    placeholder="Cohort name"
                    value={
                        displayOperatorAndValue
                            ? { value: '' }
                            : {
                                  value: value,
                                  label: cohorts?.find((cohort) => cohort.id === value)?.name || value,
                              }
                    }
                    onChange={(_, newFilter) => {
                        onComplete()
                        const { value: filterValue, type } = newFilter as { value: string; type: string }
                        setThisFilter('id', filterValue, undefined, type)
                    }}
                    data-attr="cohort-filter-select"
                    {...selectProps}
                >
                    {cohorts.map((item, index) => (
                        <Select.Option
                            className="ph-no-capture"
                            key={'cohort-filter-' + index}
                            value={item.id}
                            type="cohort"
                            data-attr={'cohort-filter-' + index}
                        >
                            {item.name}
                        </Select.Option>
                    ))}
                </SelectGradientOverflow>
            </Col>
        </Row>
    )
}

export function TabbedPropertyFilter({
    index,
    onComplete,
    logic,
    selectProps,
}: PropertyFilterInternalProps): JSX.Element {
    const { filters } = useValues(logic)
    const { setFilter } = useActions(logic)
    const { key, value, operator, type } = filters[index]
    const [activeKey, setActiveKey] = useState(type === 'cohort' ? 'cohort' : 'property')

    const displayOperatorAndValue = key && type !== 'cohort'

    const setThisFilter = (newKey: string, newValue: string, newOperator: string, newType: string): void => {
        setFilter(index, newKey, newValue, newOperator, newType)
    }

    return (
        <Tabs
            defaultActiveKey={type === 'cohort' ? 'cohort' : 'property'}
            onChange={setActiveKey}
            tabPosition="top"
            animated={false}
            style={{ minWidth: displayOperatorAndValue ? 700 : 350 }}
        >
            <TabPane
                tab="Property"
                key="property"
                style={{ display: 'flex', marginLeft: activeKey === 'cohort' ? '-100%' : 0 }}
            >
                <PropertyPaneContents
                    onComplete={onComplete}
                    setThisFilter={setThisFilter}
                    propkey={key}
                    value={value}
                    operator={operator}
                    type={type}
                    displayOperatorAndValue={displayOperatorAndValue}
                    selectProps={selectProps}
                />
            </TabPane>
            <TabPane tab="Cohort" key="cohort" style={{ display: 'flex' }}>
                <CohortPaneContents
                    onComplete={onComplete}
                    setThisFilter={setThisFilter}
                    value={value}
                    displayOperatorAndValue={displayOperatorAndValue}
                    selectProps={selectProps}
                />
                {type === 'cohort' && value ? (
                    <Link to={`/cohorts/${value}`} target="_blank">
                        <Col style={{ marginLeft: 10, marginTop: 5 }}> View </Col>
                    </Link>
                ) : null}
            </TabPane>
        </Tabs>
    )
}
