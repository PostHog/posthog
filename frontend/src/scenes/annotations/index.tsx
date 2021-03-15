import React, { useState, useEffect, HTMLAttributes } from 'react'
import { useValues, useActions } from 'kea'
import { Table, Tag, Button, Modal, Input, DatePicker, Row, Spin, Menu, Dropdown } from 'antd'
import { humanFriendlyDetailedTime } from 'lib/utils'
import moment from 'moment'
import { annotationsModel } from '~/models/annotationsModel'
import { annotationsTableLogic } from './logic'
import { DeleteOutlined, RedoOutlined, ProjectOutlined, DeploymentUnitOutlined, DownOutlined } from '@ant-design/icons'
import { AnnotationScope, annotationScopeToName } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { PlusOutlined } from '@ant-design/icons'
import { createdByColumn } from 'lib/components/Table'
import { AnnotationType } from '~/types'

const { TextArea } = Input

export function Annotations(): JSX.Element {
    const { annotations, annotationsLoading, next, loadingNext } = useValues(annotationsTableLogic)
    const { loadAnnotations, updateAnnotation, deleteAnnotation, loadAnnotationsNext, restoreAnnotation } = useActions(
        annotationsTableLogic
    )
    const { createGlobalAnnotation } = useActions(annotationsModel)
    const [open, setOpen] = useState(false)
    const [selectedAnnotation, setSelected] = useState({} as AnnotationType)

    const columns = [
        {
            title: 'Annotation',
            key: 'annotation',
            render: function RenderAnnotation(annotation: AnnotationType): JSX.Element {
                return (
                    <span
                        className="ph-no-capture"
                        style={{
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            maxWidth: 200,
                        }}
                    >
                        {annotation.content}
                    </span>
                )
            },
            ellipsis: true,
        },
        createdByColumn(annotations),
        {
            title: 'Date Marker',
            render: function RenderDateMarker(annotation: AnnotationType): JSX.Element {
                return <span>{moment(annotation.date_marker).format('YYYY-MM-DD')}</span>
            },
        },
        {
            title: 'Last Updated',
            render: function RenderLastUpdated(annotation: AnnotationType): JSX.Element {
                return <span>{humanFriendlyDetailedTime(annotation.updated_at)}</span>
            },
        },
        {
            title: 'Status',
            render: function RenderStatus(annotation: AnnotationType): JSX.Element {
                return annotation.deleted ? <Tag color="red">Deleted</Tag> : <Tag color="green">Active</Tag>
            },
        },
        {
            title: 'Type',
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
        setTimeout(() => setSelected({} as AnnotationType), 500)
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
                    ;(await selectedAnnotation)
                        ? updateAnnotation(selectedAnnotation.id, input)
                        : createGlobalAnnotation(input, selectedDate, null)
                    closeModal()
                    loadAnnotations()
                }}
                onDelete={(): void => {
                    deleteAnnotation(selectedAnnotation.id)
                    closeModal()
                }}
                onRestore={(): void => {
                    restoreAnnotation(selectedAnnotation.id)
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
    onSubmit: (input: string, date: moment.Moment) => void
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
    const [selectedDate, setDate] = useState<moment.Moment>(moment())
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
                        props.onSubmit(textInput, selectedDate)
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
                                        Project {user?.team?.name}
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
                        onChange={(date): void => setDate(date as moment.Moment)}
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
