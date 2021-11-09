import React, { useState, useEffect, HTMLAttributes } from 'react'
import { useValues, useActions } from 'kea'
import { Table, Tag, Button, Modal, Input, Row, Spin, Menu, Dropdown } from 'antd'
import { humanFriendlyDetailedTime } from 'lib/utils'
import dayjs from 'dayjs'
import { annotationsModel } from '~/models/annotationsModel'
import { annotationsTableLogic } from './logic'
import { DeleteOutlined, RedoOutlined, ProjectOutlined, DeploymentUnitOutlined, DownOutlined } from '@ant-design/icons'
import { annotationScopeToName } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { PlusOutlined } from '@ant-design/icons'
import { createdByColumn } from 'lib/components/Table/Table'
import { AnnotationType, AnnotationScope } from '~/types'

import dayjsGenerateConfig from 'rc-picker/lib/generate/dayjs'
import generatePicker from 'antd/lib/date-picker/generatePicker'
import { normalizeColumnTitle, useIsTableScrolling } from 'lib/components/Table/utils'
import { teamLogic } from '../teamLogic'
import { SceneExport } from 'scenes/sceneTypes'
const DatePicker = generatePicker<dayjs.Dayjs>(dayjsGenerateConfig)

const { TextArea } = Input

export const scene: SceneExport = {
    component: Annotations,
    logic: annotationsTableLogic,
}

export function Annotations(): JSX.Element {
    const { annotations, annotationsLoading, next, loadingNext } = useValues(annotationsTableLogic)
    const { updateAnnotation, deleteAnnotation, loadAnnotationsNext, restoreAnnotation } =
        useActions(annotationsTableLogic)
    const { createGlobalAnnotation } = useActions(annotationsModel)
    const [open, setOpen] = useState(false)
    const [selectedAnnotation, setSelected] = useState(null as AnnotationType | null)
    const { tableScrollX } = useIsTableScrolling('lg')

    const columns = [
        {
            title: normalizeColumnTitle('Annotation'),
            key: 'annotation',
            fixed: true,
            render: function RenderAnnotation(annotation: AnnotationType): JSX.Element {
                return (
                    <div
                        className="ph-no-capture"
                        style={{
                            width: 'auto',
                            maxWidth: 250,
                        }}
                    >
                        {annotation.content}
                    </div>
                )
            },
        },
        createdByColumn(annotations),
        {
            title: normalizeColumnTitle('Date Marker'),
            render: function RenderDateMarker(annotation: AnnotationType): JSX.Element {
                return <span>{dayjs(annotation.date_marker).format('YYYY-MM-DD')}</span>
            },
        },
        {
            title: normalizeColumnTitle('Last Updated'),
            render: function RenderLastUpdated(annotation: AnnotationType): JSX.Element {
                return <span>{humanFriendlyDetailedTime(annotation.updated_at)}</span>
            },
        },
        {
            title: normalizeColumnTitle('Status'),
            render: function RenderStatus(annotation: AnnotationType): JSX.Element {
                return annotation.deleted ? <Tag color="red">Deleted</Tag> : <Tag color="green">Active</Tag>
            },
        },
        {
            title: normalizeColumnTitle('Type'),
            render: function RenderType(annotation: AnnotationType): JSX.Element {
                return annotation.scope !== 'dashboard_item' ? (
                    <Tag color="blue">Global</Tag>
                ) : (
                    <Tag color="purple">Dashboard Item</Tag>
                )
            },
        },
    ]

    function closeModal(): void {
        setOpen(false)
        setTimeout(() => setSelected(null as AnnotationType | null), 500)
    }

    return (
        <div>
            <PageHeader
                title="Annotations"
                caption="Here you can add organization- and project-wide annotations. Dashboard-specific ones can be added directly in the dashboard."
            />

            <div>
                <div className="mb text-right">
                    <Button
                        type="primary"
                        data-attr="create-annotation"
                        onClick={(): void => setOpen(true)}
                        icon={<PlusOutlined />}
                    >
                        Create Annotation
                    </Button>
                </div>
                <Table
                    data-attr="annotations-table"
                    size="small"
                    rowKey="id"
                    pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                    rowClassName="cursor-pointer"
                    dataSource={annotations}
                    columns={columns}
                    loading={annotationsLoading}
                    onRow={(annotation): HTMLAttributes<HTMLElement> => ({
                        onClick: (): void => {
                            setSelected(annotation)
                            setOpen(true)
                        },
                    })}
                    scroll={{ x: tableScrollX }}
                />
                <div
                    style={{
                        visibility: next ? 'visible' : 'hidden',
                        margin: '2rem auto 5rem',
                        textAlign: 'center',
                    }}
                >
                    {loadingNext ? (
                        <Spin />
                    ) : (
                        <Button
                            type="primary"
                            onClick={(): void => {
                                loadAnnotationsNext()
                            }}
                        >
                            {'Load more annotations'}
                        </Button>
                    )}
                </div>
            </div>
            <CreateAnnotationModal
                visible={open}
                onCancel={(): void => {
                    closeModal()
                }}
                onSubmit={async (input, selectedDate): Promise<void> => {
                    if (selectedAnnotation && (await selectedAnnotation)) {
                        updateAnnotation(selectedAnnotation.id, input)
                    } else {
                        createGlobalAnnotation(input, selectedDate.format('YYYY-MM-DD'))
                    }
                    closeModal()
                }}
                onDelete={(): void => {
                    if (selectedAnnotation) {
                        deleteAnnotation(selectedAnnotation.id)
                    }
                    closeModal()
                }}
                onRestore={(): void => {
                    if (selectedAnnotation) {
                        restoreAnnotation(selectedAnnotation.id)
                    }
                    closeModal()
                }}
                annotation={selectedAnnotation}
            />
        </div>
    )
}

interface CreateAnnotationModalProps {
    visible: boolean
    onCancel: () => void
    onDelete: () => void
    onRestore: () => void
    onSubmit: (input: string, date: dayjs.Dayjs) => void
    annotation?: any
}

enum ModalMode {
    CREATE,
    EDIT,
}

function CreateAnnotationModal(props: CreateAnnotationModalProps): JSX.Element {
    const [scope, setScope] = useState<AnnotationScope>(AnnotationScope.Project)
    const [textInput, setTextInput] = useState('')
    const [modalMode, setModalMode] = useState<ModalMode>(ModalMode.CREATE)
    const [selectedDate, setDate] = useState<dayjs.Dayjs>(dayjs())
    const { currentTeam } = useValues(teamLogic)
    const { user } = useValues(userLogic)

    useEffect(() => {
        if (props.annotation) {
            setModalMode(ModalMode.EDIT)
            setTextInput(props.annotation.content)
        } else {
            setModalMode(ModalMode.CREATE)
            setTextInput('')
        }
    }, [props.annotation])

    const _onSubmit = (input: string, date: dayjs.Dayjs): void => {
        props.onSubmit(input, date)
        setTextInput('')
        setDate(dayjs())
        setScope(AnnotationScope.Project)
    }

    return (
        <Modal
            footer={[
                <Button key="create-annotation-cancel" onClick={(): void => props.onCancel()}>
                    Cancel
                </Button>,
                <Button
                    type="primary"
                    key="create-annotation-submit"
                    data-attr="create-annotation-submit"
                    onClick={(): void => {
                        _onSubmit(textInput, selectedDate)
                    }}
                >
                    {modalMode === ModalMode.CREATE ? 'Submit' : 'Update'}
                </Button>,
            ]}
            closable={false}
            visible={props.visible}
            onCancel={props.onCancel}
            title={modalMode === ModalMode.CREATE ? 'Create Global Annotation' : 'Edit Annotation'}
        >
            {modalMode === ModalMode.CREATE ? (
                <span>
                    This annotation will appear on all
                    <Dropdown
                        overlay={
                            <Menu>
                                {scope === AnnotationScope.Project ? (
                                    <Menu.Item
                                        onClick={() => {
                                            setScope(AnnotationScope.Project)
                                        }}
                                        key={AnnotationScope.Project}
                                        icon={<ProjectOutlined />}
                                    >
                                        Project {currentTeam?.name}
                                    </Menu.Item>
                                ) : (
                                    <Menu.Item
                                        onClick={() => {
                                            setScope(AnnotationScope.Organization)
                                        }}
                                        key={AnnotationScope.Organization}
                                        icon={<DeploymentUnitOutlined />}
                                    >
                                        Organization {user?.organization?.name}
                                    </Menu.Item>
                                )}
                            </Menu>
                        }
                    >
                        <Button style={{ marginLeft: 8, marginRight: 8 }}>
                            {annotationScopeToName.get(scope)} <DownOutlined />
                        </Button>
                    </Dropdown>{' '}
                    charts
                </span>
            ) : (
                <Row justify="space-between">
                    <span>Change existing annotation text</span>
                    {!props.annotation?.deleted ? (
                        <DeleteOutlined
                            className="text-danger"
                            onClick={(): void => {
                                props.onDelete()
                            }}
                        />
                    ) : (
                        <RedoOutlined
                            className="button-border clickable"
                            onClick={(): void => {
                                props.onRestore()
                            }}
                        />
                    )}
                </Row>
            )}
            <br />
            {modalMode === ModalMode.CREATE && (
                <div>
                    Date:
                    <DatePicker
                        style={{ marginTop: 16, marginLeft: 8, marginBottom: 16 }}
                        getPopupContainer={(trigger): HTMLElement => trigger.parentElement as HTMLElement}
                        value={selectedDate}
                        onChange={(date): void => setDate(date as dayjs.Dayjs)}
                        allowClear={false}
                    />
                </div>
            )}
            <TextArea
                data-attr="create-annotation-input"
                maxLength={300}
                style={{ marginBottom: 12, marginTop: 5 }}
                rows={4}
                value={textInput}
                onChange={(e): void => setTextInput(e.target.value)}
            />
        </Modal>
    )
}
