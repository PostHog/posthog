import React from 'react'
import { Table } from 'antd'
import { Link } from 'lib/components/Link'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import { PersonType } from '~/types'
import { IconPerson } from 'lib/components/icons'
import { ArrowRightOutlined } from '@ant-design/icons'
import './Persons.scss'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import moment from 'moment'
import { midEllipsis } from 'lib/utils'

interface PersonsTableType {
    people: PersonType[]
    loading?: boolean
}

export function PersonsTable({ people, loading = false }: PersonsTableType): JSX.Element {
    const linkToPerson = (person: PersonType): string => {
        return `/person/${encodeURIComponent(person.distinct_ids[0])}`
    }

    const columns = [
        {
            title: 'Email',
            key: 'email',
            render: function Render(_: string, person: PersonType) {
                return (
                    <Link to={linkToPerson(person)} data-attr="goto-person-email">
                        {person.is_identified ? (
                            <div className="user-email identified">
                                <IconPerson />{' '}
                                {person.properties.email ? (
                                    <span className={rrwebBlockClass}>{person.properties.email}</span>
                                ) : (
                                    <i>No email recorded</i>
                                )}
                            </div>
                        ) : (
                            <div className="user-email anonymous">
                                <IconPerson /> Anonymous user
                            </div>
                        )}
                    </Link>
                )
            },
        },
        {
            title: 'ID',
            key: 'id',
            render: function Render(_: string, person: PersonType) {
                return (
                    <div>
                        <CopyToClipboardInline
                            explicitValue={person.distinct_ids[0]}
                            tooltipMessage=""
                            iconStyle={{ color: 'var(--primary)' }}
                        >
                            {midEllipsis(person.distinct_ids[0], 32)}
                        </CopyToClipboardInline>
                    </div>
                )
            },
        },
        {
            title: 'First seen',
            key: 'created',
            render: function Render(_: string, person: PersonType) {
                return <> {moment(person.created_at).fromNow()}</>
            },
        },
        {
            key: 'actions',
            render: function Render(_: string, person: PersonType) {
                return (
                    <>
                        <Link to={linkToPerson(person)} data-attr="goto-person-arrow">
                            <ArrowRightOutlined /> view
                        </Link>
                    </>
                )
            },
        },
    ]

    return (
        <Table
            size="small"
            columns={columns}
            loading={loading}
            rowKey="id"
            pagination={{ pageSize: 99999, hideOnSinglePage: true }}
            expandable={{
                expandedRowRender: function RenderPropertiesTable({ properties }) {
                    return <PropertiesTable properties={properties} />
                },
                rowExpandable: ({ properties }) => Object.keys(properties).length > 0,
            }}
            dataSource={people}
            className="persons-table"
        />
    )
}
