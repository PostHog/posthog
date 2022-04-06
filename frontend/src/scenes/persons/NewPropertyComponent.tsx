import React, { useState } from 'react'
import { Input, Radio } from 'antd'
import { SaveOutlined, StopOutlined, CheckOutlined, CloseOutlined } from '@ant-design/icons'
import Modal from 'antd/lib/modal/Modal'
import { LemonButton } from 'lib/components/LemonButton'

interface NewPropertyInterface {
    creating: boolean
    propertyType: 'string' | 'boolean'
    key?: string | null
    value?: string | number | boolean | null
}

export interface NewPropertyComponentProps {
    editProperty: (key: string, newValue?: string | number | boolean | null) => void
}

export function NewPropertyComponent({ editProperty }: NewPropertyComponentProps): JSX.Element {
    const initialState = { creating: false, propertyType: 'string' } as NewPropertyInterface
    const [state, setState] = useState(initialState)

    const saveProperty = (): void => {
        if (state.key && state.value !== undefined) {
            editProperty(state.key, state.value)
            setState(initialState)
        }
    }

    return (
        <>
            <div className="mb">
                <div className="text-right">
                    <LemonButton
                        data-attr="add-prop-button"
                        onClick={() => setState({ ...state, creating: true })}
                        type="primary"
                    >
                        New property
                    </LemonButton>
                </div>
            </div>
            <Modal
                visible={state.creating}
                destroyOnClose
                onCancel={() => setState(initialState)}
                title="Adding new property"
                okText={
                    <>
                        <SaveOutlined style={{ marginRight: 4 }} />
                        Save Property
                    </>
                }
                okButtonProps={{ disabled: !state.key || state.value === undefined }}
                onOk={saveProperty}
            >
                <div className="input-set">
                    <label htmlFor="propertyKey">Key</label>
                    <Input
                        id="propertyKey"
                        autoFocus
                        placeholder="try email, first_name, is_verified, membership_level, total_revenue"
                        onChange={(e) => setState({ ...state, key: e.target.value })}
                    />
                </div>
                <div className="input-set">
                    <label htmlFor="propertyType">Type of Property</label>
                    <div>
                        <Radio.Group
                            value={state.propertyType}
                            onChange={(e) =>
                                setState({
                                    ...state,
                                    propertyType: e.target.value,
                                    value: e.target.value === 'string' ? undefined : 'true',
                                })
                            }
                            id="propertyType"
                            buttonStyle="solid"
                        >
                            <Radio.Button value="string">Text or Number</Radio.Button>
                            <Radio.Button value="boolean">Boolean or Null</Radio.Button>
                        </Radio.Group>
                    </div>
                </div>

                <div className="input-set">
                    <label htmlFor="propertyValue">Value</label>
                    {state.propertyType === 'boolean' ? (
                        <div>
                            <Radio.Group
                                value={state.value}
                                onChange={(e) =>
                                    setState({
                                        ...state,
                                        value: e.target.value,
                                    })
                                }
                                id="propertyValue"
                                buttonStyle="solid"
                            >
                                <Radio.Button value="true" defaultChecked>
                                    <CheckOutlined /> True
                                </Radio.Button>
                                <Radio.Button value="false">
                                    <CloseOutlined /> False
                                </Radio.Button>
                                <Radio.Button value="null">
                                    <StopOutlined /> Null
                                </Radio.Button>
                            </Radio.Group>
                        </div>
                    ) : (
                        <Input
                            placeholder="try email@example.com, gold, 1"
                            onChange={(e) => setState({ ...state, value: e.target.value })}
                            id="propertyValue"
                            onKeyDown={(e) => e.key === 'Enter' && saveProperty()}
                        />
                    )}
                </div>
            </Modal>
        </>
    )
}
