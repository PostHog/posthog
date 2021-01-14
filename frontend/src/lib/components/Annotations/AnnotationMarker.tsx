import React, { useState, useEffect, useRef } from 'react'
import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { Button, Popover, Row, Input, Checkbox, Tooltip } from 'antd'
import { humanFriendlyDetailedTime } from '~/lib/utils'
import { DeleteOutlined, PlusOutlined, ProjectOutlined, DeploymentUnitOutlined, CloseOutlined } from '@ant-design/icons'
import { annotationsLogic } from './annotationsLogic'
import moment from 'moment'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import { dashboardColors } from 'lib/colors'
import { AnnotationScope } from 'lib/constants'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

const { TextArea } = Input

function coordinateContains(e, element): boolean {
    if (
        e.clientX >= element.x &&
        e.clientX <= element.x + element.width &&
        e.clientY >= element.y &&
        e.clientY <= element.y + element.height
    ) {
        return true
    } else {
        return false
    }
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
}: Record<string, any>): JSX.Element | null {
    const popupRef = useRef<HTMLDivElement | null>(null)
    const [focused, setFocused] = useState(false)
    const [textInput, setTextInput] = useState('')
    const [applyAll, setApplyAll] = useState(true)
    const [textAreaVisible, setTextAreaVisible] = useState(false)
    const [hovered, setHovered] = useState(false)
    const { reportAnnotationViewed } = useActions(eventUsageLogic)

    const visible = focused || (!dynamic && hovered)

    useEffect(() => {
        if (visible) {
            reportAnnotationViewed(annotations)
        } else {
            reportAnnotationViewed(null)
            /* We report a null value to cancel (if applicable) the report because the annotation was closed */
        }
    }, [visible])

    const {
        user: { id, name, email, organization, project },
    } = useValues(userLogic)

    const { diffType, groupedAnnotations } = useValues(
        annotationsLogic({
            pageKey: dashboardItemId ? dashboardItemId : null,
        })
    )

    function closePopup(): void {
        setFocused(false)
        onClose?.()
    }

    useEscapeKey(closePopup, [focused])

    const _color = color || 'var(--primary)'
    const _accessoryColor = accessoryColor || 'white'

    function deselect(e): void {
        if (popupRef.current && coordinateContains(e, popupRef.current.getBoundingClientRect())) {
            return
        }
        closePopup()
    }

    useEffect(() => {
        document.addEventListener('mousedown', deselect)
        return () => {
            document.removeEventListener('mousedown', deselect)
        }
    }, [])

    if (
        dynamic &&
        Object.keys(groupedAnnotations)
            .map((key) => moment(key))
            .some((marker) => marker.isSame(moment(currentDateMarker).startOf(diffType)))
    ) {
        return null
    }

    return (
        <Popover
            trigger="click"
            visible={visible}
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
                            checked={applyAll}
                            onChange={(e) => {
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
                                    onCreateAnnotation?.(textInput, applyAll)
                                    setTextInput('')
                                }}
                            >
                                Add
                            </Button>
                        </Row>
                    </div>
                ) : (
                    <div ref={popupRef} style={{ minWidth: 300 }}>
                        {[...annotations]
                            .sort((annotationA, annotationB) => annotationA.created_at - annotationB.created_at)
                            .map((data) => (
                                <div key={data.id} style={{ marginBottom: 25 }}>
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
                                            {data.scope === AnnotationScope.Project ? (
                                                <Tooltip
                                                    title={`This annotation is shown on all charts in project ${project.name}`}
                                                >
                                                    <ProjectOutlined />
                                                </Tooltip>
                                            ) : data.scope === AnnotationScope.Organization ? (
                                                <Tooltip
                                                    title={`This annotation is shown on all charts in organization ${organization.name}`}
                                                >
                                                    <DeploymentUnitOutlined />
                                                </Tooltip>
                                            ) : null}
                                        </div>
                                        {(!data.created_by ||
                                            data.created_by.id === id ||
                                            data.created_by === 'local') && (
                                            <DeleteOutlined
                                                className="button-border clickable text-danger"
                                                onClick={() => {
                                                    onDelete(data)
                                                }}
                                            />
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
                                checked={applyAll}
                                onChange={(e) => {
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
                                    type="primary"
                                    onClick={() => {
                                        setTextAreaVisible(true)
                                    }}
                                >
                                    Add Note
                                </Button>
                            </Row>
                        )}
                    </div>
                )
            }
            title={
                <Row justify="space-between" align="middle" style={{ lineHeight: '30px' }}>
                    {label}
                    {focused && (
                        <CloseOutlined
                            className="button-border clickable"
                            onClick={() => {
                                setFocused(false)
                                onClose?.()
                            }}
                        />
                    )}
                </Row>
            }
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
                        focused || dynamic || hovered || elementId === currentDateMarker
                            ? _color
                            : dashboardColors[graphColor] || 'white',
                    borderRadius: 5,
                    cursor: 'pointer',
                    border: dynamic ? undefined : '1px solid ' + _color,
                    zIndex: dynamic || hovered || elementId === currentDateMarker ? 999 : index,
                    boxShadow: dynamic ? '0 0 5px 4px rgba(0, 0, 0, 0.2)' : undefined,
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
                            color: focused || hovered || elementId === currentDateMarker ? _accessoryColor : _color,

                            fontSize: 12,
                        }}
                    >
                        {annotations.length}
                    </span>
                ) : (
                    <PlusOutlined style={{ color: _accessoryColor }} />
                )}
            </div>
        </Popover>
    )
}
