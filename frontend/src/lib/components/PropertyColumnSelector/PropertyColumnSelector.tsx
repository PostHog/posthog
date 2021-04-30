import React, { ReactElement, useState } from 'react'
import { Modal, Button } from 'antd'
import { CheckboxValueType } from 'antd/lib/checkbox/Group'
import './PropertyColumnSelector.scss'
import { useValues } from 'kea'
import { propertyDefinitionsLogic } from 'scenes/events/propertyDefinitionsLogic'
import { PropertySelect } from '../PropertyFilters/PropertySelect'
import { SelectOption } from '~/types'
import { CloseButton } from '../CloseButton'

type onConfirmCallback = (options: CheckboxValueType[]) => any
type onCancelCallback = (options: CheckboxValueType[]) => any

interface PropertyColumnSelectorProps {
    onConfirm?: onConfirmCallback
    onCancel?: onCancelCallback
    title: string
    visible: boolean
    selectedItems: CheckboxValueType[]
}

export function PropertyColumnSelector(props: PropertyColumnSelectorProps): ReactElement | null {
    const { title, onConfirm, onCancel, selectedItems = [''], visible = false } = props
    const [checkedValues, setCheckedValues] = useState(selectedItems)
    const _onConfirm = (): void => {
        if (onConfirm) {
            onConfirm(checkedValues)
        }
    }
    const _onCancel = (): void => {
        if (onCancel) {
            onCancel(checkedValues)
        }
        setCheckedValues(selectedItems)
    }

    const { propertyDefinitions, loaded } = useValues(propertyDefinitionsLogic)
    return (
        <>
            <Modal
                centered
                title={title}
                visible={visible}
                onOk={_onConfirm}
                confirmLoading={!loaded}
                onCancel={_onCancel}
                width={700}
                bodyStyle={{
                    maxHeight: '520px',
                    overflow: 'auto',
                }}
                className="items-selector-modal"
                okButtonProps={{
                    className: 'items-selector-confirm',
                }}
            >
                {JSON.stringify(checkedValues)}
                {checkedValues.map((value, index) => (
                    <>
                        <PropertySelect
                            key={index}
                            optionGroups={[
                                {
                                    type: 'event',
                                    label: 'Events',
                                    options: propertyDefinitions.map((d) => ({ value: d.name })),
                                },
                            ]}
                            placeholder="Select property"
                            value={value !== '' ? ({ value, label: value } as SelectOption) : null}
                            onChange={(_, value) => {
                                const arr = [...checkedValues]
                                arr[index] = value
                                setCheckedValues(arr)
                            }}
                        />
                        <CloseButton
                            className="ml-1"
                            onClick={() => {
                                const arr = [...checkedValues]
                                arr.splice(index, 1)
                                setCheckedValues(arr)
                            }}
                            style={{ cursor: 'pointer', float: 'none', marginLeft: 5 }}
                        />
                    </>
                ))}
                <Button onClick={() => setCheckedValues([...checkedValues, ''])}>Add column</Button>
            </Modal>
        </>
    )
}
