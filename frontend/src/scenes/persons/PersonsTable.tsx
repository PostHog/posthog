import React, { useRef } from 'react'
import { Button } from 'antd'
import { Link } from 'lib/components/Link'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { CohortType, PersonType } from '~/types'
import { ArrowRightOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import './Persons.scss'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import dayjs from 'dayjs'
import { midEllipsis } from 'lib/utils'
import { PersonHeader } from './PersonHeader'

import relativeTime from 'dayjs/plugin/relativeTime'
import { TZLabel } from 'lib/components/TimezoneAware'
import { ResizableColumnType, ResizableTable } from 'lib/components/ResizableTable'
dayjs.extend(relativeTime)

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
        const backTo = cohort
            ? `#backTo=Cohorts&backToURL=${window.location.pathname}`
            : `#backTo=Persons&backToURL=${window.location.pathname}`
        return `/person/${encodeURIComponent(person.distinct_ids[0])}${backTo}`
    }

    const topRef = useRef<HTMLSpanElement>(null)

    const columns: ResizableColumnType<PersonType>[] = [
        {
            title: 'Email',
            key: 'email',
            span: 6,
            render: function Render(person: PersonType) {
                return (
                    <Link to={linkToPerson(person)} data-attr="goto-person-email">
                        <PersonHeader person={person} />
                    </Link>
                )
            },
        },
        {
            title: 'ID',
            key: 'id',
            span: 8,
            render: function Render(person: PersonType) {
                return (
                    <div style={{ overflow: 'hidden' }}>
                        {person.distinct_ids.length && (
                            <CopyToClipboardInline
                                explicitValue={person.distinct_ids[0]}
                                tooltipMessage=""
                                iconStyle={{ color: 'var(--primary)' }}
                                iconPosition="end"
                            >
                                {midEllipsis(person.distinct_ids[0], 32)}
                            </CopyToClipboardInline>
                        )}
                    </div>
                )
            },
        },
    ]

    if (allColumns) {
        columns.push({
            title: 'First seen',
            key: 'created',
            span: 3,
            render: function Render(person: PersonType) {
                return person.created_at ? <TZLabel time={person.created_at} /> : <></>
            },
        })
    }

    columns.push({
        key: 'actions',
        title: '',
        span: 2,
        render: function Render(person: PersonType, ...[, index]: [PersonType, number]) {
            return (
                <>
                    <Link to={linkToPerson(person)} data-attr={`goto-person-arrow-${index}`} data-test-goto-person>
                        <ArrowRightOutlined style={{ float: 'right' }} />
                        {allColumns ? ' view' : ''}
                    </Link>
                </>
            )
        },
    })

    return (
        <>
            <span ref={topRef} />
            <ResizableTable
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
