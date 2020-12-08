import React, { useRef } from 'react'
import { Button, Table } from 'antd'
import { Link } from 'lib/components/Link'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import { CohortType, PersonType } from '~/types'
import { IconPerson } from 'lib/components/icons'
import { ArrowRightOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import './Persons.scss'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import moment from 'moment'
import { midEllipsis } from 'lib/utils'

interface PersonsTableType {
    people: PersonType[]
    loading?: boolean
    hasPrevious?: boolean
    hasNext?: boolean
    loadPrevious?: () => void
    loadNext?: () => void
    allColumns?: boolean // whether to show all columns or not
    cohort?: CohortType
}

export function PersonsTable({
    people,
    loading = false,
    hasPrevious,
    hasNext,
    loadPrevious,
    loadNext,
    allColumns,
    cohort,
}: PersonsTableType): JSX.Element {
    const linkToPerson = (person: PersonType): string => {
        const backTo = cohort ? `#backTo=Back%20to%20Cohorts&backToURL=/cohorts/${cohort.id}` : ''
        return `/person/${encodeURIComponent(person.distinct_ids[0])}${backTo}`
    }

    const topRef = useRef<HTMLSpanElement>(null)

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
    ]

    if (allColumns) {
        columns.push({
            title: 'First seen',
            key: 'created',
            render: function Render(_: string, person: PersonType) {
                return <> {moment(person.created_at).fromNow()}</>
            },
        })
    }

    columns.push({
        key: 'actions',
        title: '',
        render: function Render(_: string, person: PersonType) {
            return (
                <>
                    <Link to={linkToPerson(person)} data-attr="goto-person-arrow">
                        <ArrowRightOutlined />
                        {allColumns ? ' view' : ''}
                    </Link>
                </>
            )
        },
    })

    return (
        <>
            <span ref={topRef} />
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
            {(hasPrevious || hasNext) && (
                <div style={{ margin: '3rem auto 10rem', width: 200, display: 'flex', alignItems: 'center' }}>
                    <Button
                        type="link"
                        disabled={!hasPrevious}
                        onClick={() => loadPrevious && loadPrevious() && window.scrollTo(0, 0)}
                    >
                        <LeftOutlined /> Previous
                    </Button>
                    <Button
                        type="link"
                        disabled={!hasNext}
                        onClick={() => loadNext && loadNext() && window.scrollTo(0, 0)}
                    >
                        Next <RightOutlined />
                    </Button>
                </div>
            )}
        </>
    )
}
