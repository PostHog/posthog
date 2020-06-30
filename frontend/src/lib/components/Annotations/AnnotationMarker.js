import './AnnotationMarker.scss'

import React, { useState } from 'react'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { Button, Popover, Row, Input } from 'antd'
const { TextArea } = Input
import { humanFriendlyDetailedTime } from '~/lib/utils'
import { DeleteOutlined } from '@ant-design/icons'
import _ from 'lodash'

export function AnnotationMarker({ label, annotations, left, top, onCreate, onDelete }) {
    const [textInput, setTextInput] = useState('')
    const [textAreaVisible, setTextAreaVisible] = useState(false)
    const {
        user: { name, email },
    } = useValues(userLogic)

    return (
        <Popover
            trigger="click"
            defaultVisible={false}
            content={
                <div style={{ minWidth: 300 }}>
                    {_.orderBy(annotations, ['created_at'], ['asc']).map(data => (
                        <div key={data.id} style={{ marginBottom: 25 }}>
                            <Row justify="space-between" align="middle">
                                <div>
                                    <b style={{ marginRight: 5 }}>
                                        {(data.created_by && (data.created_by.first_name || data.created_by.email)) ||
                                            name ||
                                            email}
                                    </b>
                                    <i style={{ color: 'gray' }}>{humanFriendlyDetailedTime(data.created_at)}</i>
                                </div>
                                <DeleteOutlined
                                    className="clickable"
                                    onClick={() => {
                                        onDelete(data.id)
                                    }}
                                ></DeleteOutlined>
                            </Row>
                            <span>{data.content}</span>
                        </div>
                    ))}
                    {textAreaVisible && (
                        <TextArea
                            style={{ marginBottom: 12 }}
                            rows={4}
                            value={textInput}
                            onChange={e => setTextInput(e.target.value)}
                        ></TextArea>
                    )}
                    {textAreaVisible ? (
                        <Row justify="end">
                            <Button
                                type="primary"
                                onClick={() => {
                                    onCreate(textInput)
                                    setTextInput('')
                                    setTextAreaVisible(false)
                                }}
                            >
                                Add
                            </Button>
                        </Row>
                    ) : (
                        <Row justify="end">
                            <Button
                                type="primary"
                                onClick={() => {
                                    setTextAreaVisible(true)
                                }}
                            >
                                Add Annotation
                            </Button>
                        </Row>
                    )}
                </div>
            }
            title={
                <Row justify="space-between" align="middle">
                    {label}
                </Row>
            }
        >
            <div
                style={{
                    position: 'absolute',
                    left: left,
                    top: top,
                    width: 25,
                    height: 25,
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                    backgroundColor: '#1890ff',
                    borderRadius: 5,
                    cursor: 'pointer',
                }}
                type="primary"
            >
                <span style={{ color: 'white', fontSize: 12 }}>{annotations.length}</span>
            </div>
        </Popover>
    )
}
