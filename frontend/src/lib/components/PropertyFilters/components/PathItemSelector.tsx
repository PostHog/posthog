import React, { useState } from 'react'
import { useValues } from 'kea'
import { Popup } from 'lib/components/Popup/Popup'
import { PathType } from '~/types'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { pathOptionsToLabels, pathOptionsToProperty, PathItem } from 'scenes/paths/pathsLogic'
import { Col, Select } from 'antd'
import { PropertyValue } from '..'

interface PathItemSelectorProps {
    pathItem: PathItem
    onChange: (item: PathItem) => void
    children: JSX.Element
    index: number
}

export function PathItemSelector({ pathItem, onChange, children }: PathItemSelectorProps): JSX.Element {
    const { customEventNames } = useValues(eventDefinitionsModel)
    const [visible, setVisible] = useState(false)

    return (
        <Popup
            visible={visible}
            placement={'bottom-end'}
            fallbackPlacements={['bottom-start']}
            onClickOutside={() => setVisible(false)}
            overlay={
                <div className={`taxonomic-property-filter in-dropdown small`}>
                    <div className="taxonomic-filter-row symmetric">
                        <Col>
                            <span>Path type:</span>
                        </Col>
                        <Col>
                            <Select
                                value={pathItem.type}
                                defaultValue={PathType.PageView}
                                dropdownMatchSelectWidth={false}
                                onChange={(value): void => onChange({ type: value, item: undefined })}
                                style={{ paddingTop: 2 }}
                            >
                                {Object.entries(pathOptionsToLabels).map(([value, name], index) => {
                                    return (
                                        <Select.Option key={index} value={value}>
                                            {name}
                                        </Select.Option>
                                    )
                                })}
                            </Select>
                        </Col>
                        <Col style={{ textAlign: 'end' }}>Path item:</Col>
                        <Col>
                            <PropertyValue
                                outerOptions={
                                    pathItem.type === PathType.CustomEvent
                                        ? customEventNames.map((name) => ({
                                              name,
                                          }))
                                        : undefined
                                }
                                onSet={(value: string): void => {
                                    onChange({
                                        ...pathItem,
                                        item: value,
                                    })
                                    setVisible(false)
                                }}
                                propertyKey={pathOptionsToProperty[pathItem.type || PathType.PageView]}
                                type="event"
                                style={{ paddingTop: 2 }}
                                value={pathItem.item}
                                placeholder={'Select start element'}
                                autoFocus={false}
                            />
                        </Col>
                    </div>
                </div>
            }
        >
            {({ setRef }) => {
                return (
                    <div ref={setRef} onClick={() => setVisible(true)}>
                        {children}
                    </div>
                )
            }}
        </Popup>
    )
}
