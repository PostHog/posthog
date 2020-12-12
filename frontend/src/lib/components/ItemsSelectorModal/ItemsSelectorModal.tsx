import React, { ReactElement, useState } from 'react'
import { Modal, Checkbox, Row, Col } from 'antd'
import { CheckboxValueType, CheckboxOptionType } from 'antd/lib/checkbox/Group'
import './ItemsSelectorModal.scss'

type onConfirmCallback = (options: CheckboxValueType[]) => any
type onCancelCallback = (options: CheckboxValueType[]) => any

interface ItemsSelectorModalProps {
    options: CheckboxOptionType[]
    onConfirm?: onConfirmCallback
    onCancel?: onCancelCallback
    title: string
    visible: boolean
    loading: boolean
    selectedItems: CheckboxValueType[]
}

export function ItemsSelectorModal(props: ItemsSelectorModalProps): ReactElement | null {
    const { title, onConfirm, onCancel, selectedItems = [], options = [], visible = false, loading = false } = props
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

    const onChange = (checkedValues: Array<CheckboxValueType>): void => {
        setCheckedValues(checkedValues)
    }

    return (
        <>
            <Modal
                centered
                title={title}
                visible={visible}
                onOk={_onConfirm}
                confirmLoading={loading}
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
                <Checkbox.Group style={{ width: '100%' }} value={checkedValues} onChange={onChange}>
                    <Row>
                        {options.map((option, index) => (
                            <Col key={index} span={8}>
                                <Checkbox className={'items-selector-checkbox'} value={option['value']}>
                                    {option['label']}
                                </Checkbox>
                            </Col>
                        ))}
                    </Row>
                </Checkbox.Group>
            </Modal>
        </>
    )
}
