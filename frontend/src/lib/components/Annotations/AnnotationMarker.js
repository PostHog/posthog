import './AnnotationMarker.scss'

import React, { useState } from 'react'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { Button, Popover, Row, Input } from 'antd'
const { TextArea } = Input
import { humanFriendlyDetailedTime } from '~/lib/utils'
import { CloseOutlined, DeleteOutlined } from '@ant-design/icons'
import _ from 'lodash'

export function AnnotationMarker({ annotations, left, top, onCreate, onDelete }) {
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
                                    <b>
                                        {(data.created_by && (data.created_by.first_name || data.created_by.email)) ||
                                            name ||
                                            email}
                                    </b>
                                    <span>{humanFriendlyDetailedTime(data.created_at)}</span>
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
                    {'Annotation'}
                    <CloseOutlined></CloseOutlined>
                </Row>
            }
        >
            <Button
                style={{
                    position: 'absolute',
                    left: left,
                    top: top,
                    width: 30,
                    height: 30,
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                }}
                type="primary"
            >
                <span>{annotations.length}</span>
            </Button>
        </Popover>
    )
}
