import React from 'react'
import { Row, Col, Input, Button } from 'antd'
import { useActions, useValues } from 'kea'
import { personsLogic } from './personsLogic'

export const AddNewPropertyField = (): JSX.Element => {
    const { newProperty, editingNewProperty } = useValues(personsLogic)
    const { setNewProperty, saveNewProperty } = useActions(personsLogic)

    return (
        <>
            {editingNewProperty ? (
                <>
                    <Row>
                        <Col span={12}>
                            <Input
                                style={{ maxWidth: '90%' }}
                                placeholder="key"
                                onChange={(e) =>
                                    setNewProperty([(e.target as HTMLInputElement).value, newProperty[1] || ''])
                                }
                            />
                        </Col>
                        <Col span={12}>
                            <Input
                                style={{ maxWidth: '90%' }}
                                placeholder="value"
                                onChange={(e) =>
                                    setNewProperty([newProperty[0] || '', (e.target as HTMLInputElement).value])
                                }
                            />
                        </Col>
                    </Row>
                    <br />
                </>
            ) : null}

            <Button
                className="add-prop-button"
                onClick={editingNewProperty ? () => saveNewProperty() : () => setNewProperty(['', ''])}
            >
                {editingNewProperty ? 'Save' : '+'}
            </Button>
        </>
    )
}
