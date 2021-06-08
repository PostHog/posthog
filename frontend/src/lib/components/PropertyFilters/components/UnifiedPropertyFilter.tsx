/*
Contains the **new** property filter (see #4050) component where all filters are unified in a single view
*/
import React, { useRef, useState } from 'react'
import { Button, Col, Row } from 'antd'
import { keyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { cohortsModel } from '~/models/cohortsModel'
import { useValues, useActions } from 'kea'
import { Link } from '../../Link'
import {
    DownOutlined,
    InfoCircleOutlined,
    ContainerOutlined,
    UserOutlined,
    UsergroupAddOutlined,
    PlusOutlined,
} from '@ant-design/icons'
import {
    OperatorValueFilterType,
    OperatorValueSelect,
} from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { humanFriendlyDetailedTime, isOperatorMulti, isOperatorRegex } from 'lib/utils'
import { SelectBox, SelectBoxItem, SelectedItem } from 'lib/components/SelectBox'
import { PropertyFilterInternalProps } from './PropertyFilter'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'

import './UnifiedPropertyFilter.scss'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

function FilterDropdown({ open, children }: { open: boolean; children: React.ReactNode }): JSX.Element | null {
    return open ? <div>{children}</div> : null
}

function EventPropertiesInfo({ item }: { item: SelectedItem }): JSX.Element {
    const info = keyMapping.event[item.name]
    return (
        <>
            Event properties
            <br />
            <h3>
                <PropertyKeyInfo value={item.name} disablePopover={true} />
            </h3>
            {info?.description && <p>{info.description}</p>}
            {info?.examples?.length && (
                <p>
                    <i>Example: </i>
                    {info.examples.join(', ')}
                </p>
            )}
            <hr />
            <p>
                Sent as <code>{item.name}</code>
            </p>
        </>
    )
}

function CohortPropertiesInfo({ item }: { item: SelectedItem }): JSX.Element {
    return (
        <>
            Cohorts
            <br />
            <h3>{item.name}</h3>
            {item.cohort && (
                <p>
                    {item.cohort?.is_static ? (
                        <>
                            <InfoCircleOutlined /> This is a static cohort.
                        </>
                    ) : (
                        <>
                            <InfoCircleOutlined /> This is a dynamically updated cohort.
                        </>
                    )}
                    <br />
                    {item.cohort?.created_at && (
                        <>
                            <i>Created: </i>
                            {humanFriendlyDetailedTime(item.cohort?.created_at)}
                            <br />
                        </>
                    )}
                </p>
            )}
        </>
    )
}

export function UnifiedPropertyFilter({ index, onComplete, logic }: PropertyFilterInternalProps): JSX.Element {
    // TODO: PersonPropertiesInfo (which will require making new entries in `keyMapping`)
    const { filters } = useValues(logic)

    const { personProperties } = useValues(personPropertiesModel)
    const { transformedPropertyDefinitions: eventProperties } = useValues(propertyDefinitionsModel)
    const { cohorts } = useValues(cohortsModel)
    const { setFilter } = useActions(logic)
    const { reportPropertySelectOpened } = useActions(eventUsageLogic)
    const { key, value, operator, type } = filters[index]
    const [open, setOpen] = useState(false)
    const selectBoxToggleRef = useRef<HTMLElement>(null)
    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)

    const displayOperatorAndValue = key && type !== 'cohort'

    const setThisFilter = (
        newKey: string,
        newValue: OperatorValueFilterType | undefined,
        newOperator: string | undefined,
        newType: string
    ): void => {
        setFilter(index, newKey, newValue, newOperator, newType)
    }

    const selectBoxItems: SelectBoxItem[] = [
        {
            name: 'Event properties',
            header: function eventPropertiesHeader(label: string) {
                return (
                    <>
                        <ContainerOutlined /> {label}
                    </>
                )
            },
            dataSource:
                eventProperties.map(({ value: eventValue, label, is_numerical }) => ({
                    name: label || '',
                    key: `event_${eventValue}`,
                    eventValue,
                    is_numerical,
                })) || [],
            renderInfo: EventPropertiesInfo,
            type: 'event',
            key: 'events',
            getValue: (item) => item.name || '',
            getLabel: (item) => item.name || '',
        },
        {
            name: 'User properties',
            header: function personPropertiesHeader(label: string) {
                return (
                    <>
                        <UserOutlined /> {label}
                    </>
                )
            },
            dataSource:
                personProperties.map(({ name }) => ({
                    name,
                    key: `person_${name}`,
                })) || [],
            renderInfo: function personPropertiesRenderInfo({ item }) {
                return (
                    <>
                        User properties
                        <br />
                        <h3>{item.name}</h3>
                        {(item?.volume_30_day ?? 0 > 0) && (
                            <>
                                Seen <strong>{item.volume_30_day}</strong> times.{' '}
                            </>
                        )}
                        {(item?.query_usage_30_day ?? 0 > 0) && (
                            <>
                                Used in <strong>{item.query_usage_30_day}</strong> queries.
                            </>
                        )}
                    </>
                )
            },
            type: 'person',
            key: 'persons',
            getValue: (item) => item.name || '',
            getLabel: (item) => item.name || '',
        },
        {
            name: 'Cohorts',
            header: function cohortPropertiesHeader(label: string) {
                return (
                    <>
                        <UsergroupAddOutlined /> {label}
                    </>
                )
            },
            dataSource:
                cohorts
                    ?.filter(({ deleted }) => !deleted)
                    ?.map((cohort) => ({
                        name: cohort.name || '',
                        key: `cohort_${cohort.id}`,
                        value: cohort.name,
                        cohort,
                    })) || [],
            renderInfo: CohortPropertiesInfo,
            type: 'cohort',
            key: 'cohorts',
            getValue: (item) => item.name || '',
            getLabel: (item) => item.name || '',
        },
    ]

    const onClick = (e: React.SyntheticEvent): void => {
        e.preventDefault()
        if (!open) {
            reportPropertySelectOpened()
        }
        setOpen(!open)
    }

    return (
        <>
            <Row gutter={8} wrap={isSmallScreen} className="property-filter-row">
                {key && (
                    <Col className="filter-where">
                        {index === 0 ? (
                            <>
                                <span className="arrow">&#8627;</span>
                                where
                            </>
                        ) : (
                            <span className="stateful-badge and" style={{ marginLeft: 28, fontSize: '90%' }}>
                                AND
                            </span>
                        )}
                    </Col>
                )}
                <Col className="filter-dropdown-container">
                    <Button
                        onClick={onClick}
                        style={{ display: 'flex', alignItems: 'center' }}
                        ref={selectBoxToggleRef}
                        icon={!key ? <PlusOutlined /> : null}
                        data-attr={'property-select-toggle-' + index}
                    >
                        <span className="text-overflow" style={{ maxWidth: '100%' }}>
                            {key ? <PropertyKeyInfo value={key} /> : 'Add filter'}
                        </span>
                        {key && <DownOutlined style={{ fontSize: 10 }} />}
                    </Button>
                    <FilterDropdown open={open}>
                        <SelectBox
                            disablePopover
                            selectedItemKey={undefined}
                            onDismiss={(e?: MouseEvent) => {
                                if (e?.target && selectBoxToggleRef?.current?.contains(e.target as Node)) {
                                    return
                                }
                                setOpen(false)
                            }}
                            onSelect={(itemType, _, name) => {
                                setThisFilter(name, undefined, operator, itemType)
                                setOpen(false)
                            }}
                            items={selectBoxItems}
                            inputPlaceholder="Search cohorts, and event or user properties"
                        />
                    </FilterDropdown>
                </Col>

                {displayOperatorAndValue && (
                    <OperatorValueSelect
                        type={type}
                        propkey={key}
                        operator={operator}
                        value={value}
                        onChange={(newOperator, newValue) => {
                            setThisFilter(key, newValue, newOperator, type)
                            if (
                                newOperator &&
                                newValue &&
                                !(isOperatorMulti(newOperator) || isOperatorRegex(newOperator))
                            ) {
                                onComplete()
                            }
                        }}
                        columnOptions={[
                            {
                                style: {
                                    minWidth: '6em',
                                },
                            },
                            {
                                style: {
                                    maxWidth: isSmallScreen ? 'unset' : '60%',
                                    minWidth: '11em',
                                    flexShrink: 3,
                                },
                            },
                        ]}
                        operatorSelectProps={{
                            dropdownMatchSelectWidth: 200,
                            style: { maxWidth: '100%' },
                        }}
                    />
                )}
            </Row>
            {type === 'cohort' && value ? (
                <Link to={`/cohorts/${value}`} target="_blank">
                    <Col style={{ marginLeft: 10, marginTop: 5 }}> View </Col>
                </Link>
            ) : null}
        </>
    )
}
