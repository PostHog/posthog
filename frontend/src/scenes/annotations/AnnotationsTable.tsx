import React, { useState } from 'react'
import { useValues } from 'kea'
import { Table, Tag, Button, Modal, Input } from 'antd'
import { Link } from 'lib/components/Link'
import { humanFriendlyDetailedTime } from 'lib/utils'

const { TextArea } = Input

interface Props {
    logic: any
}

export function AnnotationsTable(props: Props) {
    const { logic } = props;
    const { annotations, annotationsLoading } = useValues(logic)
    const [open, setOpen] = useState(false)
    console.log(annotations)
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
        />
        <CreateAnnotationModal visible={open} onCancel={() => setOpen(false)} onSubmit={(input) => {}}></CreateAnnotationModal>
    </div>
}

interface CreateAnnotationModalProps {
    visible: boolean,
    onCancel: () => void,
    onSubmit: (input: string) => void
}

function CreateAnnotationModal(props: CreateAnnotationModalProps) {
    const [textInput, setTextInput] = useState('')

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
                        props.onSubmit(textInput)
                    }}
                >
                    Submit
                </Button>,
            ]} 
            closable={false} 
            visible={props.visible} 
            onCancel={props.onCancel}
            title={"Create a Global Annotation"}
        >
            <span>This annotation will appear on all charts</span>
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
