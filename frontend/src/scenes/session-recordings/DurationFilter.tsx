import React from 'react'
import { PropertyOperator, RecordingDurationFilter } from '~/types'
import { Button, Row, Space } from 'antd'
import { OperatorSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { Popup } from 'lib/components/Popup/Popup'
import { durationFilterLogic } from './durationFilterLogic'
import { useActions, useValues } from 'kea'
import { DurationPicker } from 'lib/components/DurationPicker/DurationPicker'
interface Props {
    initialFilter: RecordingDurationFilter
    onChange: (value: RecordingDurationFilter) => void
    pageKey: string
}

export function DurationFilter({ initialFilter, onChange, pageKey }: Props): JSX.Element {
    const durationFilterLogicInstance = durationFilterLogic({ initialFilter, onChange, pageKey })
    const { setValue, setIsOpen, setOperator } = useActions(durationFilterLogicInstance)
    const { durationString, value, operator, isOpen } = useValues(durationFilterLogicInstance)
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
                        <DurationPicker onChange={setValue} initialValue={value || 0} key={pageKey} />
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
