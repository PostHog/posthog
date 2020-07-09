import './AnnotationMarker.scss'

import React, { useState, useEffect, useRef } from 'react'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { Button, Popover, Row, Input, Checkbox, Tooltip } from 'antd'
import { humanFriendlyDetailedTime } from '~/lib/utils'
import { DeleteOutlined, PlusOutlined, GlobalOutlined } from '@ant-design/icons'
import _ from 'lodash'
import { annotationsLogic } from './annotationsLogic'
import moment from 'moment'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'

const { TextArea } = Input

function coordinateContains(e, element) {
    if (
        e.clientX >= element.x &&
        e.clientX <= element.x + element.width &&
        e.clientY >= element.y &&
        e.clientY <= element.y + element.height
    )
        return true
    else return false
}

export function AnnotationMarker({
    elementId,
    label,
    annotations,
    left,
    top,
    onCreate,
    onDelete,
    onClick,
    size = 25,
    color,
    accessoryColor,
    dashboardItemId,
    currentDateMarker,
    onClose,
    dynamic,
    onCreateAnnotation,
    graphColor,
    index,
    onChecked,
}) {
    const popupRef = useRef()
    const draggingRef = useRef()
    const [focused, setFocused] = useState(false)
    const [textInput, setTextInput] = useState('')
    const [applyAll, setApplyAll] = useState(false)
    const [textAreaVisible, setTextAreaVisible] = useState(false)
    const [hovered, setHovered] = useState(false)
    const {
        user: { id, name, email },
    } = useValues(userLogic)

    const { diffType, groupedAnnotations } = useValues(
        annotationsLogic({
            pageKey: dashboardItemId ? dashboardItemId : null,
        })
    )

    function closePopup() {
        setFocused(false)
        onClose?.()
    }

    useEscapeKey(closePopup, [focused])

    const _color = color || '#1890ff'
    const _accessoryColor = accessoryColor || 'white'

    const deselect = (e) => {
        if (popupRef.current && coordinateContains(e, popupRef.current.getBoundingClientRect())) {
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
        dynamic &&
        Object.keys(groupedAnnotations)
            .map((key) => moment(key))
            .some((marker) => marker.isSame(moment(currentDateMarker).startOf(diffType)))
    )
        return null

    return (
        <Popover
            trigger="click"
            defaultVisible={false}
            content={
                dynamic ? (
                    <div ref={popupRef}>
                        <span style={{ marginBottom: 12 }}>{moment(currentDateMarker).format('MMMM Do YYYY')}</span>
                        <TextArea
                            maxLength={300}
                            style={{ marginBottom: 12 }}
                            rows={4}
                            value={textInput}
                            onChange={(e) => setTextInput(e.target.value)}
                        />
                        <Checkbox
                            onChange={(e) => {
                                onChecked?.(e)
                                setApplyAll(e.target.checked)
                            }}
                        >
                            Create for all charts
                        </Checkbox>
                        <Row justify="end">
                            <Button
                                style={{ marginRight: 10 }}
                                onClick={() => {
                                    closePopup()
                                    setTextInput('')
                                }}
                            >
                                Cancel
                            </Button>
                            <Button
                                type="primary"
                                onClick={() => {
                                    closePopup()
                                    onCreateAnnotation?.(textInput)
                                    setTextInput('')
                                }}
                            >
                                Add
                            </Button>
                        </Row>
                    </div>
                ) : (
                    <div ref={popupRef} style={{ minWidth: 300 }}>
                        {_.orderBy(annotations, ['created_at'], ['asc']).map((data) => (
                            <div key={data.id} style={{ marginBottom: 25, backgroundColor: 'white' }}>
                                <Row justify="space-between" align="middle">
                                    <div>
                                        <b style={{ marginRight: 5 }}>
                                            {data.created_by === 'local'
                                                ? name || email
                                                : data.created_by &&
                                                  (data.created_by.first_name || data.created_by.email)}
                                        </b>
                                        <i style={{ color: 'gray', marginRight: 6 }}>
                                            {humanFriendlyDetailedTime(data.created_at)}
                                        </i>
                                        {data.apply_all && (
                                            <Tooltip title="This note is shown on all charts">
                                                <GlobalOutlined></GlobalOutlined>
                                            </Tooltip>
                                        )}
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
                        {textAreaVisible && (
                            <Checkbox
                                onChange={(e) => {
                                    onChecked?.(e)
                                    setApplyAll(e.target.checked)
                                }}
                            >
                                Create for all charts
                            </Checkbox>
                        )}
                        {textAreaVisible ? (
                            <Row justify="end">
                                <Button style={{ marginRight: 10 }} onClick={() => setTextAreaVisible(false)}>
                                    Cancel
                                </Button>
                                <Button
                                    type="primary"
                                    onClick={() => {
                                        onCreate(textInput, applyAll)
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
            visible={focused}
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
                    backgroundColor:
                        dynamic || hovered || elementId === currentDateMarker ? _color : graphColor || 'white',
                    borderRadius: 5,
                    cursor: 'pointer',
                    border: dynamic ? null : '1px solid ' + _color,
                    zIndex: hovered || elementId === currentDateMarker ? 999 : index,
                }}
                type="primary"
                onClick={() => {
                    onClick?.()
                    setFocused(true)
                }}
                onMouseOver={() => setHovered(true)}
                onMouseLeave={() => setHovered(false)}
            >
                {annotations ? (
                    <span
                        style={{
                            color: hovered || elementId === currentDateMarker ? _accessoryColor : _color,

                            fontSize: 12,
                        }}
                    >
                        {annotations.length}
                    </span>
                ) : (
                    <PlusOutlined style={{ color: _accessoryColor }}></PlusOutlined>
                )}
            </div>
        </Popover>
    )
}
