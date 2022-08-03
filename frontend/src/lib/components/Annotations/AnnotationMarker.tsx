import React, { useState, useEffect, useRef } from 'react'
import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { Popover } from 'antd'
import { humanFriendlyDetailedTime } from '~/lib/utils'
import { PlusOutlined, ProjectOutlined, DeploymentUnitOutlined } from '@ant-design/icons'
import { annotationsLogic } from './annotationsLogic'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { AnnotationScope, AnnotationType } from '~/types'
import { styles } from '~/styles/vars'
import { teamLogic } from 'scenes/teamLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { dayjs } from 'lib/dayjs'
import { LemonTextArea } from '../LemonTextArea/LemonTextArea'
import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'
import { IconClose, IconDelete } from '../icons'

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
    elementId?: string
    label: string
    annotations?: AnnotationType[]
    left: number
    top: number
    onCreate?: (textInput: string, applyAll: boolean) => void
    onDelete?: (annotation: AnnotationType) => void
    onClick?: () => void
    onClose?: () => void
    size?: number
    color: string | null
    accessoryColor: string | null
    insightNumericId?: number
    currentDateMarker?: string | null
    dynamic?: boolean
    index?: number
    getPopupContainer?: () => HTMLElement
}

export function AnnotationMarker({
    elementId,
    label,
    annotations = [],
    left,
    top,
    onCreate,
    onDelete,
    onClick,
    size = 25,
    color,
    accessoryColor,
    insightNumericId,
    currentDateMarker,
    onClose,
    dynamic,
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
    const { diffType, groupedAnnotations } = useValues(annotationsLogic({ insightNumericId }))

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

    const _onClose = dynamic ? closePopup : () => setTextAreaVisible(false)

    const editorSection = (
        <>
            <LemonTextArea maxLength={300} rows={4} value={textInput} onChange={(e) => setTextInput(e)} autoFocus />
            <LemonCheckbox
                checked={applyAll}
                onChange={(e) => {
                    setApplyAll(e.target.checked)
                }}
                label="Create for all charts"
                rowProps={{ fullWidth: true }}
            />
            <div className="flex justify-end gap-2">
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => {
                        _onClose()
                        setTextInput('')
                    }}
                >
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => {
                        onCreate && onCreate(textInput, applyAll)
                        _onClose()
                        setTextInput('')
                    }}
                >
                    Add
                </LemonButton>
            </div>
        </>
    )

    return (
        <Popover
            trigger="click"
            visible={visible}
            defaultVisible={false}
            getPopupContainer={() => (getPopupContainer ? getPopupContainer() : document.body)}
            content={
                dynamic ? (
                    <div ref={popupRef} className="p-2" style={{ minWidth: 300 }}>
                        <div className="pb-2">{dayjs(currentDateMarker).format('MMMM Do YYYY')}</div>
                        {editorSection}
                    </div>
                ) : (
                    <div ref={popupRef} style={{ minWidth: 300 }}>
                        <div style={{ overflowY: 'auto', maxHeight: '80vh' }}>
                            {[...annotations]
                                .sort(
                                    (annotationA, annotationB) =>
                                        dayjs(annotationA.created_at).unix() - dayjs(annotationB.created_at).unix()
                                )
                                .map((data) => (
                                    <div key={data.id} className="mb-2">
                                        <div className="flex justify-between items-center">
                                            <div className="space-x-2">
                                                <b>
                                                    {data.created_by &&
                                                        (data.created_by.first_name || data.created_by.email)}
                                                </b>
                                                <i className="text-muted">
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
                                                <LemonButton
                                                    type="tertiary"
                                                    size="small"
                                                    icon={<IconDelete />}
                                                    onClick={() => onDelete?.(data)}
                                                />
                                            )}
                                        </div>
                                        <span>{data.content}</span>
                                    </div>
                                ))}
                        </div>
                        <div className="border-t pt-2">
                            {textAreaVisible ? (
                                editorSection
                            ) : (
                                <div className="flex justify-end">
                                    <LemonButton type="primary" size="small" onClick={() => setTextAreaVisible(true)}>
                                        Add Note
                                    </LemonButton>
                                </div>
                            )}
                        </div>
                    </div>
                )
            }
            title={
                <div className="flex justify-between items-center">
                    {label}
                    {focused && (
                        <LemonButton
                            type="tertiary"
                            icon={<IconClose />}
                            onClick={() => {
                                setFocused(false)
                                onClose?.()
                            }}
                        />
                    )}
                </div>
            }
        >
            <div
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    position: 'absolute',
                    left: left,
                    top: top,
                    width: size,
                    height: size,
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                    backgroundColor: focused || dynamic || hovered || elementId === currentDateMarker ? _color : '#fff',
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
                {(annotations?.length || 0) > 0 ? (
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
