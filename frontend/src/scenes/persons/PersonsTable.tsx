import React, { useRef } from 'react'
import { Button } from 'antd'
import { combineUrl } from 'kea-router'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { TZLabel } from 'lib/components/TimezoneAware'
import { Link } from 'lib/components/Link'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { PersonsTabType, PersonType, SessionsPropertyFilter } from '~/types'
import { ArrowRightOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import './Persons.scss'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { midEllipsis } from 'lib/utils'
import { PersonHeader } from './PersonHeader'
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
    backTo?: string // text to display next to `back to` arrow. if "Insights," deep link to Persons > Sessions
    sessionsFilters?: Partial<SessionsPropertyFilter>[] // sessions filters from trends graphs
    date?: string
}

export const deepLinkToPersonSessions = (
    person: PersonType,
    sessionsFilters?: Partial<SessionsPropertyFilter>[],
    date?: string,
    backTo?: string
): string =>
    combineUrl(
        `/person/${encodeURIComponent(person.distinct_ids[0])}`,
        { filters: sessionsFilters, date },
        {
            backTo,
            backToURL: window.location.pathname + window.location.search + window.location.hash,
            activeTab: backTo === 'Insights' ? PersonsTabType.SESSIONS : PersonsTabType.EVENTS,
        }
    ).url

export function PersonsTable({
    people,
    loading = false,
    hasPrevious,
    hasNext,
    loadPrevious,
    loadNext,
    allColumns,
    backTo = 'Persons',
    sessionsFilters = [],
    date = '',
}: PersonsTableType): JSX.Element {
    const topRef = useRef<HTMLSpanElement>(null)

    const columns: ResizableColumnType<PersonType>[] = [
        {
            title: 'Identification',
            key: 'identification',
            span: 6,
            render: function Render(person: PersonType) {
                return <PersonHeader person={person} />
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
                    <Link
                        to={deepLinkToPersonSessions(person, sessionsFilters, date, backTo)}
                        data-attr={`goto-person-arrow-${index}`}
                        data-test-goto-person
                    >
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
