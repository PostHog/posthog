import React, { useState, useEffect } from 'react'
import { useValues, useActions } from 'kea'
import { Table, Tag, Button, Modal, Input, DatePicker} from 'antd'
import { Link } from 'lib/components/Link'
import { humanFriendlyDetailedTime } from 'lib/utils'
import moment from 'moment'
import { annotationsModel } from '~/models/annotationsModel'

const { TextArea } = Input

interface Props {
    logic: any
}

export function AnnotationsTable(props: Props) {
    const { logic } = props;
    const { annotations, annotationsLoading } = useValues(logic)
    const { loadAnnotations } = useActions(logic)
    const { createGlobalAnnotation } = useActions(annotationsModel)
    const [open, setOpen] = useState(false)
    const [selectedAnnotation, setSelected] = useState(null)

    let columns = [
        {
            title: 'Annotation',
            key: 'annotation',
            render: function RenderAnnotation(annotation) {

                return (
                    <span style={{
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        maxWidth: 200
                    }}>
                        {annotation.content}
                    </span>
                )
            },
            ellipsis: true,
        },
        {
            title: 'Created By',
            key: 'person',
            render: function RenderPerson(annotation) {
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
            render: function RenderLastUpdated(annotation) {
                return <span>{humanFriendlyDetailedTime(annotation.updated_at)}</span>
            },
        },
        {
            title: 'Status',
            render: function RenderStatus(annotation) {
                return (annotation.deleted ? <Tag color="red">Deleted</Tag> : <Tag color="green">Active</Tag>)
            },
        },
        {
            title: 'Type',
            render: function RenderType(annotation) {
                return (annotation.apply_all ? <Tag color="blue">Global</Tag> : <Tag color="purple">Dashboard Item</Tag>)
            },
        },
    ]

    return <div>
        <h1 className="page-header">Annotations</h1>
        <Button className="mb-4" type="primary" data-attr="create-annotation" onClick={() => setOpen(true)}>
            + Create Global Annotation
        </Button>
        <Table
            data-attr="annotations-table"
            size="small"
            rowKey={(item) => item.id}
            pagination={{ pageSize: 99999, hideOnSinglePage: true }}
            rowClassName="cursor-pointer"
            dataSource={annotations}
            columns={columns}
            loading={annotationsLoading}
            onRow={(annotation) => ({
                onClick: () => {
                    setSelected(annotation)
                    setOpen(true)
                },
            })}
        />
        <CreateAnnotationModal 
            visible={open} 
            onCancel={() => {
                setOpen(false)
                setTimeout(() => setSelected(null), 500)
                
            }} 
            onSubmit={(input, selectedDate) => {
                createGlobalAnnotation(input, selectedDate, null)
                setOpen(false)
                setTimeout(() => setSelected(null), 500)
                loadAnnotations()
            }} 
            annotation={selectedAnnotation}
        ></CreateAnnotationModal>
    </div>
}

interface CreateAnnotationModalProps {
    visible: boolean,
    onCancel: () => void,
    onSubmit: (input: string, date: moment.Moment) => void,
    annotation?: any
}

enum ModalMode {
    CREATE,
    EDIT
}

function CreateAnnotationModal(props: CreateAnnotationModalProps) {
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
                <Button key="create-annotation-cancel" onClick={() => props.onCancel()}>
                    Cancel
                </Button>
                ,
                <Button
                    type="primary"
                    key="create-annotation-submit"
                    onClick={() => {
                        props.onSubmit(textInput, selectedDate)
                    }}
                >
                    {modalMode === ModalMode.CREATE ? "Submit" : "Update"}
                </Button>,
            ]} 
            closable={false} 
            visible={props.visible} 
            onCancel={props.onCancel}
            title={modalMode === ModalMode.CREATE ? "Create Global Annotation" : "Edit Annotation"}
        >
            {modalMode === ModalMode.CREATE ? <span>This annotation will appear on all charts</span> : <span>Change existing annotation text</span>}
            <br></br>
            {modalMode === ModalMode.CREATE &&  
            <div>
                Date: 
                <DatePicker className="mb-2 mt-2 ml-2" getPopupContainer={(trigger) => trigger.parentElement} value={selectedDate} onChange={(date) => setDate(date)} allowClear={false}></DatePicker>
            </div>}
            <TextArea 
                maxLength={300}
                style={{ marginBottom: 12, marginTop: 12 }}
                rows={4}
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}>

            </TextArea>
        </Modal>
    )
}
