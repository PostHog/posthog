import React from 'react'
import { TZLabel } from 'lib/components/TimezoneAware'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { PersonType } from '~/types'
import './Persons.scss'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { PersonHeader } from './PersonHeader'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'

interface PersonsTableType {
    people: PersonType[]
    loading?: boolean
    hasPrevious?: boolean
    hasNext?: boolean
    loadPrevious?: () => void
    loadNext?: () => void
    compact?: boolean
}

export function PersonsTable({
    people,
    loading = false,
    hasPrevious,
    hasNext,
    loadPrevious,
    loadNext,
    compact,
}: PersonsTableType): JSX.Element {
    const columns: LemonTableColumns<PersonType> = [
        {
            title: 'Person',
            key: 'person',
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
                                iconStyle={{ color: 'var(--primary)' }}
                                description="person distinct ID"
                            >
                                {person.distinct_ids[0]}
                            </CopyToClipboardInline>
                        )}
                    </div>
                )
            },
        },
        ...(!compact
            ? [
                  {
                      title: 'First seen',
                      dataIndex: 'created_at',
                      render: function Render(created_at: PersonType['created_at']) {
                          return created_at ? <TZLabel time={created_at} /> : <></>
                      },
                  } as LemonTableColumn<PersonType, keyof PersonType | undefined>,
              ]
            : []),
    ]

    return (
        <LemonTable
            columns={columns}
            loading={loading}
            rowKey="id"
            pagination={{
                controlled: true,
                pageSize: 100, // From `posthog/api/person.py`
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
                    return Object.keys(properties).length ? (
                        <PropertiesTable properties={properties} />
                    ) : (
                        'This person has no properties.'
                    )
                },
            }}
            dataSource={people}
            emptyState="No persons"
            nouns={['person', 'persons']}
        />
    )
}
