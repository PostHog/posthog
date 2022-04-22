import React from 'react'
import { PropertyOperator, RecordingDurationFilter } from '~/types'
import { Button, Input, Row, Select, Space } from 'antd'
import { OperatorSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { Popup } from 'lib/components/Popup/Popup'
import { durationFilterLogic, TimeUnit } from './durationFilterLogic'
import { useActions, useValues } from 'kea'
interface Props {
    initialFilter: RecordingDurationFilter
    onChange: (value: RecordingDurationFilter) => void
    pageKey: string
}

export function DurationFilter({ initialFilter, onChange, pageKey }: Props): JSX.Element {
    const durationFilterLogicInstance = durationFilterLogic({ initialFilter, onChange, pageKey })
    const { setTimeValue, setIsOpen, setOperator, setUnit } = useActions(durationFilterLogicInstance)
    const { durationString, unit, timeValue, operator, isOpen } = useValues(durationFilterLogicInstance)
    return (
        <Popup
            visible={isOpen}
            placement={'bottom-end'}
            fallbackPlacements={['bottom-start']}
            onClickOutside={() => setIsOpen(false)}
            overlay={
                <Row>
                    <Space>
                        <OperatorSelect
                            operator={operator}
                            operators={[PropertyOperator.GreaterThan, PropertyOperator.LessThan]}
                            onChange={(newOperator) => {
                                setOperator(newOperator)
                            }}
                        />
                        <Input
                            type="number"
                            value={timeValue ?? undefined}
                            placeholder="0"
                            min={0}
                            autoFocus
                            addonAfter={
                                <Select
                                    showSearch={false}
                                    value={unit}
                                    onChange={(newUnit: TimeUnit) => {
                                        setUnit(newUnit)
                                    }}
                                >
                                    <Select.Option value="seconds">Seconds</Select.Option>
                                    <Select.Option value="minutes">Minutes</Select.Option>
                                    <Select.Option value="hours">Hours</Select.Option>
                                </Select>
                            }
                            step={1}
                            onChange={(event) => {
                                const newValue = event.target.value ? parseFloat(event.target.value) : null
                                setTimeValue(newValue)
                            }}
                        />
                    </Space>
                </Row>
            }
        >
            <Button
                onClick={() => {
                    setIsOpen(true)
                }}
            >
                {durationString}
            </Button>
        </Popup>
    )
}
