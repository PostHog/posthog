import React, { useState } from 'react'
import { Row, Col, Input, Button, Select } from 'antd'
import { useActions, useValues } from 'kea'
import { personsLogic } from './personsLogic'
import { PlusOutlined, CloseOutlined, CheckOutlined, BulbOutlined } from '@ant-design/icons'
import { IconText } from 'lib/components/icons'

interface NewPropertyInterface {
    creating: boolean
    key?: string | null
    value?: string | number | boolean | null
}

export const NewPropertyComponent = (): JSX.Element => {
    const initialState = { creating: false } as NewPropertyInterface
    const [state, setState] = useState(initialState)
    const { newProperty, editingNewProperty } = useValues(personsLogic)
    const { setNewProperty, saveNewProperty } = useActions(personsLogic)

    return (
        <div className="mb">
            {state.creating ? (
                <>
                    <h3 className="l3" style={{ marginBottom: 16 }}>
                        Adding new property
                    </h3>
                    <Row gutter={8}>
                        <Col span={1}>
                            <span
                                className="cursor-pointer text-muted"
                                style={{ height: '100%', display: 'flex', alignItems: 'center', paddingRight: 16 }}
                                onClick={() => setState(initialState)}
                            >
                                <CloseOutlined />
                            </span>
                        </Col>
                        <Col span={11}>
                            <Input
                                autoFocus
                                placeholder="Key"
                                onChange={(e) =>
                                    setNewProperty([(e.target as HTMLInputElement).value, newProperty[1] || ''])
                                }
                            />
                        </Col>
                        <Col span={11}>
                            <Input.Group compact>
                                <Select defaultValue="string">
                                    <Select.Option value="string">
                                        <IconText />
                                    </Select.Option>
                                    <Select.Option value="boolean">
                                        <BulbOutlined />
                                    </Select.Option>
                                </Select>
                                <Input
                                    style={{ width: 'calc(100% - 56px)' }}
                                    placeholder="Value"
                                    onChange={(e) =>
                                        setNewProperty([newProperty[0] || '', (e.target as HTMLInputElement).value])
                                    }
                                />
                            </Input.Group>
                        </Col>
                        <Col span={1}>
                            <span
                                className="cursor-pointer text-success"
                                style={{ height: '100%', display: 'flex', alignItems: 'center' }}
                                onClick={() => setState(initialState)}
                            >
                                <CheckOutlined />
                            </span>
                        </Col>
                    </Row>
                </>
            ) : (
                <div className="text-right">
                    <Button
                        data-attr="add-prop-button"
                        onClick={() => setState({ ...state, creating: true })}
                        type="primary"
                        icon={<PlusOutlined />}
                    >
                        New property
                    </Button>
                </div>
            )}
        </div>
    )
}
