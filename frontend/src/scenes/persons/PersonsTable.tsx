import React, { useRef } from 'react'
import { Button } from 'antd'
import { combineUrl } from 'kea-router'
import { TZLabel } from 'lib/components/TimezoneAware'
import { Link } from 'lib/components/Link'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { PersonType, SessionsPropertyFilter } from '~/types'
import { ArrowRightOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import './Persons.scss'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { midEllipsis } from 'lib/utils'
import { PersonHeader } from './PersonHeader'
import { ResizableColumnType, ResizableTable } from 'lib/components/ResizableTable'
import { urls } from 'scenes/urls'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable/LemonTable'
import { LemonButton } from 'lib/components/LemonButton'
import { More } from 'lib/components/LemonButton/More'

interface PersonsTableType {
    people: PersonType[]
    loading?: boolean
    hasPrevious?: boolean
    hasNext?: boolean
    loadPrevious?: () => void
    loadNext?: () => void
    allColumns?: boolean // whether to show all columns or not
    sessionsFilters?: Partial<SessionsPropertyFilter>[] // sessions filters from trends graphs
    date?: string
}

export const deepLinkToPersonSessions = (
    person: PersonType,
    sessionsFilters?: Partial<SessionsPropertyFilter>[],
    date?: string
): string => combineUrl(urls.person(person.distinct_ids[0]), { filters: sessionsFilters, date }).url

export function PersonsTable({
    people,
    loading = false,
    hasPrevious,
    hasNext,
    loadPrevious,
    loadNext,
    allColumns,
    sessionsFilters = [],
    date = '',
}: PersonsTableType): JSX.Element {
    const topRef = useRef<HTMLSpanElement>(null)

    const columns: LemonTableColumns<PersonType> = [
        {
            title: 'Identification',
            key: 'identification',
            render: function Render(_, person: PersonType) {
                return <PersonHeader withIcon person={person} />
            },
        },
        {
            title: 'ID',
            key: 'id',
            render: function Render(_, person: PersonType) {
                return (
                    <div style={{ overflow: 'hidden' }}>
                        {person.distinct_ids.length && (
                            <CopyToClipboardInline
                                explicitValue={person.distinct_ids[0]}
                                tooltipMessage={null}
                                iconStyle={{ color: 'var(--primary)' }}
                                iconPosition="end"
                                description="person ID"
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
            render: function Render(_, person: PersonType) {
                return person.created_at ? <TZLabel time={person.created_at} /> : <></>
            },
        })
    }

    columns.push({
        key: 'actions',
        width: 0,
        render: function Render(_, person: PersonType, index) {
            return (
                <More
                    overlay={
                        <LemonButton
                            type="stealth"
                            to={deepLinkToPersonSessions(person, sessionsFilters, date)}
                            data-attr={`goto-person-arrow-${index}`}
                            data-test-goto-person
                        >
                            View
                        </LemonButton>
                    }
                />
            )
        },
    })

    return (
        <>
            <span ref={topRef} />
            <LemonTable
                columns={columns}
                loading={loading}
                rowKey="id"
                pagination={{
                    controlled: true,
                    pageSize: 100,
                    onForward: hasNext
                        ? () => {
                              loadNext?.()
                              window.scrollTo(0, 0)
                          }
                        : undefined,
                    onBackward: hasPrevious
                        ? () => {
                              loadPrevious?.()
                              window.scrollTo(0, 0)
                          }
                        : undefined,
                }}
                expandable={{
                    expandedRowRender: function RenderPropertiesTable({ properties }) {
                        return <PropertiesTable properties={properties} />
                    },
                    rowExpandable: ({ properties }) => Object.keys(properties).length > 0,
                }}
                dataSource={people}
                nouns={['person', 'persons']}
                className="persons-table"
            />
        </>
    )
}
