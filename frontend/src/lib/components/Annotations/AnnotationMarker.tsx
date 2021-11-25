import React, { useState, useEffect, useRef } from 'react'
import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { Button, Popover, Row, Input, Checkbox } from 'antd'
import { humanFriendlyDetailedTime } from '~/lib/utils'
import { DeleteOutlined, PlusOutlined, ProjectOutlined, DeploymentUnitOutlined, CloseOutlined } from '@ant-design/icons'
import { annotationsLogic } from './annotationsLogic'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import { dashboardColors } from 'lib/colors'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { AnnotationScope, AnnotationType } from '~/types'
import { styles } from '~/vars'
import { teamLogic } from 'scenes/teamLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { dayjs } from 'lib/dayjs'

const { TextArea } = Input

function coordinateContains(e: MouseEvent, element: DOMRect): boolean {
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

interface AnnotationMarkerProps {
    elementId: string
    label: string
    annotations: AnnotationType[]
    left: number
    top: number
    onCreate: (textInput: string, applyAll: boolean) => void
    onDelete?: (annotation: AnnotationType) => void
    onClick?: () => void
    onClose?: () => void
    onCreateAnnotation?: (textInput: string, applyAll: boolean) => void
    size?: number
    color: string | null
    accessoryColor: string | null
    insightId?: number
    currentDateMarker: string
    dynamic?: boolean
    graphColor: string | null
    index: number
    getPopupContainer?: () => HTMLElement
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
    insightId,
    currentDateMarker,
    onClose,
    dynamic,
    onCreateAnnotation,
    graphColor,
    index,
    getPopupContainer,
}: AnnotationMarkerProps): JSX.Element | null {
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

    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const { diffType, groupedAnnotations } = useValues(annotationsLogic({ insightId: insightId }))

    function closePopup(): void {
        setFocused(false)
        onClose?.()
    }

    useEscapeKey(closePopup, [focused])

    const _color = color || 'var(--primary)'
    const _accessoryColor = accessoryColor || 'white'

    function deselect(e: MouseEvent): void {
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
            .map((key) => dayjs(key))
            .some((marker) => marker.isSame(dayjs(currentDateMarker).startOf(diffType as dayjs.OpUnitType)))
    ) {
        return null
    }

    return (
        <Popover
            trigger="click"
            visible={visible}
            defaultVisible={false}
            getPopupContainer={() => (getPopupContainer ? getPopupContainer() : document.body)}
            content={
                dynamic ? (
                    <div ref={popupRef}>
                        <div style={{ padding: '12px 16px' }}>
                            <span style={{ marginBottom: 12 }}>{dayjs(currentDateMarker).format('MMMM Do YYYY')}</span>
                            <TextArea
                                maxLength={300}
                                style={{ marginBottom: 12 }}
                                rows={4}
                                value={textInput}
                                onChange={(e) => setTextInput(e.target.value)}
                                autoFocus
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
                    </div>
                ) : (
                    <div ref={popupRef} style={{ minWidth: 300 }}>
                        <div style={{ overflowY: 'auto', maxHeight: '80vh', padding: '12px 16px 0 16px' }}>
                            {[...annotations]
                                .sort(
                                    (annotationA, annotationB) =>
                                        dayjs(annotationA.created_at).unix() - dayjs(annotationB.created_at).unix()
                                )
                                .map((data) => (
                                    <div key={data.id} style={{ marginBottom: 25 }}>
                                        <Row justify="space-between" align="middle">
                                            <div>
                                                <b style={{ marginRight: 5 }}>
                                                    {data.created_by &&
                                                        (data.created_by.first_name || data.created_by.email)}
                                                </b>
                                                <i style={{ color: 'gray', marginRight: 6 }}>
                                                    {humanFriendlyDetailedTime(data.created_at)}
                                                </i>
                                                {data.scope === AnnotationScope.Project ? (
                                                    <Tooltip
                                                        title={`This annotation is shown on all charts in project ${currentTeam?.name}`}
                                                    >
                                                        <ProjectOutlined />
                                                    </Tooltip>
                                                ) : data.scope === AnnotationScope.Organization ? (
                                                    <Tooltip
                                                        title={`This annotation is shown on all charts in organization ${currentOrganization?.name}`}
                                                    >
                                                        <DeploymentUnitOutlined />
                                                    </Tooltip>
                                                ) : null}
                                            </div>
                                            {(!data.created_by || data.created_by.uuid === user?.uuid) && (
                                                <DeleteOutlined
                                                    className="button-border clickable text-danger"
                                                    onClick={() => onDelete?.(data)}
                                                />
                                            )}
                                        </Row>
                                        <span>{data.content}</span>
                                    </div>
                                ))}
                        </div>
                        <div style={{ padding: '12px 16px', borderTop: '1px solid #f0f0f0' }}>
                            {textAreaVisible ? (
                                <>
                                    <TextArea
                                        maxLength={300}
                                        style={{ marginBottom: 12 }}
                                        rows={4}
                                        value={textInput}
                                        onChange={(e) => setTextInput(e.target.value)}
                                        autoFocus
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
                                </>
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
                            : (graphColor ? dashboardColors[graphColor] : null) || 'white',
                    borderRadius: 5,
                    cursor: 'pointer',
                    border: dynamic ? undefined : '1px solid ' + _color,
                    zIndex:
                        dynamic || hovered || elementId === currentDateMarker ? styles.zGraphAnnotationPrompt : index,
                    boxShadow: dynamic ? '0 0 5px 4px rgba(0, 0, 0, 0.2)' : undefined,
                }}
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
