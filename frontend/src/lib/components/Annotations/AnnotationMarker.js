import './AnnotationMarker.scss'

import React, { useState, useEffect, useRef } from 'react'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { Button, Popover, Row, Input } from 'antd'
import { humanFriendlyDetailedTime } from '~/lib/utils'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import _ from 'lodash'
import { annotationsLogic } from './annotationsLogic'
import moment from 'moment'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'

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
    dashboardItemId,
    currentDateMarker,
    onClose,
}) {
    const popupRef = useRef()
    const draggingRef = useRef()
    const [localVisibilityControl, setVisibilityControl] = useState(true)
    const [focused, setFocused] = useState(false)
    const [textInput, setTextInput] = useState('')
    const [textAreaVisible, setTextAreaVisible] = useState(false)
    const {
        user: { id, name, email },
    } = useValues(userLogic)

    const { diffType, groupedAnnotations } = useValues(
        annotationsLogic({
            pageKey: dashboardItemId ? dashboardItemId : null,
        })
    )

    function closePopup() {
        if (localVisibilityControl) {
            setFocused(false)
            onClose?.()
        }
    }

    useEscapeKey(closePopup, [focused])

    const _color = color || '#1890ff'
    const _accessoryColor = accessoryColor || 'white'

    useEffect(() => {
        if (visible !== null && visible !== undefined) {
            setVisibilityControl(false)
        }
    }, [])

    const deselect = (e) => {
        if (popupRef.current && popupRef.current.contains(e.target)) {
            draggingRef.current = {
                x: e.clientX,
                y: e.clientY,
            }
            return
        }
        closePopup()
    }

    const onMouseMove = () => {
        if (draggingRef.current) {
            const { x, y } = draggingRef.current
            const distance = Math.round(Math.sqrt(Math.pow(y - event.clientY, 2) + Math.pow(x - event.clientX, 2)))
            if (distance > 30) closePopup()
        }
    }

    function onMouseUp() {
        draggingRef.current = false
    }

    useEffect(() => {
        document.addEventListener('mousedown', deselect)
        return () => {
            document.removeEventListener('mousedown', deselect)
        }
    }, [])

    useEffect(() => {
        document.addEventListener('mouseup', onMouseUp)
        return () => {
            document.removeEventListener('mouseup', onMouseUp)
        }
    }, [])

    useEffect(() => {
        document.addEventListener('mousemove', onMouseMove)
        return () => {
            document.removeEventListener('mousemove', onMouseMove)
        }
    }, [])

    if (
        Object.keys(groupedAnnotations)
            .map((key) => moment(key))
            .some((marker) => marker.isSame(moment(currentDateMarker).startOf(diffType))) &&
        !visible
    )
        return null

    return (
        <Popover
            trigger="click"
            defaultVisible={false}
            content={
                content ? (
                    content
                ) : (
                    <div ref={popupRef} style={{ minWidth: 300 }}>
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
                                <Button style={{ marginRight: 10 }} onClick={() => setTextAreaVisible(false)}>
                                    Cancel
                                </Button>
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
                                    style={{ marginRight: 10 }}
                                    onClick={() => {
                                        setFocused(false)
                                        onClose?.()
                                    }}
                                >
                                    Close
                                </Button>
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
            visible={localVisibilityControl ? focused : visible}
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
                    border: content ? '1px solid white' : null,
                }}
                type="primary"
                onClick={() => {
                    onClick?.()
                    localVisibilityControl && setFocused(true)
                }}
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
