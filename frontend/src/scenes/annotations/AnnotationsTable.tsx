import React, { useState, useEffect, HTMLAttributes } from 'react'
import { useValues, useActions } from 'kea'
import { Table, Tag, Button, Modal, Input, DatePicker, Row, Spin } from 'antd'
import { Link } from 'lib/components/Link'
import 'lib/components/Annotations/AnnotationMarker.scss'
import { humanFriendlyDetailedTime } from 'lib/utils'
import moment from 'moment'
import { annotationsModel } from '~/models/annotationsModel'
import { DeleteOutlined } from '@ant-design/icons'

const { TextArea } = Input

interface Props {
    logic: any
}

export function AnnotationsTable(props: Props): JSX.Element {
    const { logic } = props
    const { annotations, annotationsLoading, next, loadingNext } = useValues(logic)
    const { loadAnnotations, updateAnnotation, deleteAnnotation, loadAnnotationsNext } = useActions(logic)
    const { createGlobalAnnotation } = useActions(annotationsModel)
    const [open, setOpen] = useState(false)
    const [selectedAnnotation, setSelected] = useState(null)

    const columns = [
        {
            title: 'Annotation',
            key: 'annotation',
            render: function RenderAnnotation(annotation): JSX.Element {
                return (
                    <span
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
        {
            title: 'Created By',
            key: 'person',
            render: function RenderPerson(annotation): JSX.Element {
                const { created_by } = annotation

                return (
                    <Link to={`/person/${encodeURIComponent(created_by.id)}`} className="ph-no-capture">
                        {created_by?.name || created_by?.email}
                    </Link>
                )
            },
            ellipsis: true,
        },
        {
            title: 'Last Updated',
            render: function RenderLastUpdated(annotation): JSX.Element {
                return <span>{humanFriendlyDetailedTime(annotation.updated_at)}</span>
            },
        },
        {
            title: 'Status',
            render: function RenderStatus(annotation): JSX.Element {
                return annotation.deleted ? <Tag color="red">Deleted</Tag> : <Tag color="green">Active</Tag>
            },
        },
        {
            title: 'Type',
            render: function RenderType(annotation): JSX.Element {
                return annotation.apply_all ? <Tag color="blue">Global</Tag> : <Tag color="purple">Dashboard Item</Tag>
            },
        },
    ]

    function closeModal(): void {
        setOpen(false)
        setTimeout(() => setSelected(null), 500)
    }

    return (
        <div>
            <h1 className="page-header">Annotations</h1>
            <p style={{ maxWidth: 600 }}>
                <i>
                    Edit an annotation by clicking on one below. You can add global annotations here. Dashboard specific
                    annotations can be added directly on the dashboard.
                </i>
            </p>
            <Button className="mb-4" type="primary" data-attr="create-annotation" onClick={(): void => setOpen(true)}>
                + Create Global Annotation
            </Button>
            <Table
                data-attr="annotations-table"
                size="small"
                rowKey={(item): string => item.id}
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
                    <Spin></Spin>
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
                annotation={selectedAnnotation}
            ></CreateAnnotationModal>
        </div>
    )
}

interface CreateAnnotationModalProps {
    visible: boolean
    onCancel: () => void
    onDelete: () => void
    onSubmit: (input: string, date: moment.Moment) => void
    annotation?: any
}

enum ModalMode {
    CREATE,
    EDIT,
}

function CreateAnnotationModal(props: CreateAnnotationModalProps): JSX.Element {
    const [textInput, setTextInput] = useState('')
    const [modalMode, setModalMode] = useState<ModalMode>(ModalMode.CREATE)
    const [selectedDate, setDate] = useState<moment.Moment>(moment())

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
                <span>This annotation will appear on all charts</span>
            ) : (
                <Row justify="space-between">
                    <span>Change existing annotation text</span>
                    <DeleteOutlined
                        className="clickable"
                        onClick={(): void => {
                            props.onDelete()
                        }}
                    ></DeleteOutlined>
                </Row>
            )}
            <br></br>
            {modalMode === ModalMode.CREATE && (
                <div>
                    Date:
                    <DatePicker
                        className="mb-2 mt-2 ml-2"
                        getPopupContainer={(trigger): HTMLElement => trigger.parentElement}
                        value={selectedDate}
                        onChange={(date): void => setDate(date)}
                        allowClear={false}
                    ></DatePicker>
                </div>
            )}
            <TextArea
                maxLength={300}
                style={{ marginBottom: 12, marginTop: 5 }}
                rows={4}
                value={textInput}
                onChange={(e): void => setTextInput(e.target.value)}
            ></TextArea>
        </Modal>
    )
}
