import React from 'react'
import { useValues } from 'kea'
import { Table, Tag } from 'antd'
import { Link } from 'lib/components/Link'
import { humanFriendlyDetailedTime } from 'lib/utils'

interface Props {
    logic: any
}

export function AnnotationsTable(props: Props) {
    const { logic } = props;
    const { annotations, annotationsLoading } = useValues(logic)
    
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
    console.log(annotations)
    return <div>
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
    </div>
}
