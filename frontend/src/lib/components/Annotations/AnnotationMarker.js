import './AnnotationMarker.scss'

import React, { useState } from 'react'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { Button, Popover, Row, Input } from 'antd'
import { humanFriendlyDetailedTime } from '~/lib/utils'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import _ from 'lodash'

const { TextArea } = Input

export function AnnotationMarker({
    label,
    annotations,
    left,
    top,
    onCreate,
    onDelete,
    onClick,
    visible,
    content,
    size = 25,
    color,
    accessoryColor,
}) {
    const [textInput, setTextInput] = useState('')
    const [textAreaVisible, setTextAreaVisible] = useState(false)
    const {
        user: { id, name, email },
    } = useValues(userLogic)

    const _color = color || '#1890ff'
    const _accessoryColor = accessoryColor || 'white'

    return (
        <Popover
            trigger="click"
            defaultVisible={false}
            content={
                content ? (
                    content
                ) : (
                    <div style={{ minWidth: 300 }}>
                        {_.orderBy(annotations, ['created_at'], ['asc']).map((data) => (
                            <div key={data.id} style={{ marginBottom: 25 }}>
                                <Row justify="space-between" align="middle">
                                    <div>
                                        <b style={{ marginRight: 5 }}>
                                            {data.created_by === 'local'
                                                ? name || email
                                                : data.created_by &&
                                                  (data.created_by.first_name || data.created_by.email)}
                                        </b>
                                        <i style={{ color: 'gray' }}>{humanFriendlyDetailedTime(data.created_at)}</i>
                                    </div>
                                    {(!data.created_by || data.created_by.id === id || data.created_by === 'local') && (
                                        <DeleteOutlined
                                            className="clickable"
                                            onClick={() => {
                                                onDelete(data.id)
                                            }}
                                        ></DeleteOutlined>
                                    )}
                                </Row>
                                <span>{data.content}</span>
                            </div>
                        ))}
                        {textAreaVisible && (
                            <TextArea
                                maxLength={300}
                                style={{ marginBottom: 12 }}
                                rows={4}
                                value={textInput}
                                onChange={(e) => setTextInput(e.target.value)}
                                autoFocus
                            />
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
                )
            }
            title={
                <Row justify="space-between" align="middle">
                    {label}
                </Row>
            }
            {...{ ...(visible !== null && visible !== undefined && { visible }) }}
        >
            <div
                style={{
                    position: 'absolute',
                    left: left,
                    top: top,
                    width: size,
                    height: size,
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                    backgroundColor: _color,
                    borderRadius: 5,
                    cursor: 'pointer',
                }}
                type="primary"
                onClick={onClick}
            >
                {annotations ? (
                    <span style={{ color: _accessoryColor, fontSize: 12 }}>{annotations.length}</span>
                ) : (
                    <PlusOutlined style={{ color: _accessoryColor }}></PlusOutlined>
                )}
            </div>
        </Popover>
    )
}
