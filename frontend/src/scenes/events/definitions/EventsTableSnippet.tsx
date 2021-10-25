import { Table } from 'antd'
import { useValues } from 'kea'
import { Property } from 'lib/components/Property'
import { TZLabel } from 'lib/components/TimezoneAware'
import React from 'react'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { PersonType } from '~/types'
import { definitionDrawerLogic } from './definitionDrawerLogic'

export function EventsTableSnippet(): JSX.Element {
    const { eventsSnippet } = useValues(definitionDrawerLogic)
    const columns = [
        {
            title: 'Person',
            key: 'person',
            render: function renderPerson({ person }: { person: PersonType }) {
                return person ? <PersonHeader withIcon person={person} /> : { props: { colSpan: 0 } }
            },
        },
        {
            title: 'URL',
            key: 'url',
            eventProperties: ['$current_url', '$screen_name'],
            span: 4,
            render: function renderURL({ properties }: { properties: any }) {
                return properties ? (
                    <Property
                        value={properties['$current_url'] ? properties['$current_url'] : properties['$screen_name']}
                    />
                ) : (
                    { props: { colSpan: 0 } }
                )
            },
            ellipsis: true,
        },
        {
            title: 'Source',
            key: 'source',
            render: function renderSource({ properties }: { properties: any }) {
                return properties ? <Property value={properties['$browser']} /> : { props: { colSpan: 0 } }
            },
        },
        {
            title: 'When',
            key: 'when',
            render: function renderWhen({ timestamp }: { timestamp: string }) {
                return timestamp ? <TZLabel time={timestamp} showSeconds /> : { props: { colSpan: 0 } }
            },
            ellipsis: true,
        },
    ]
    return (
        <>
            {eventsSnippet && (
                <div style={{ fontWeight: 400, paddingTop: 15 }}>
                    <Table
                        dataSource={eventsSnippet}
                        columns={columns}
                        key={'default'}
                        rowKey={(row) => row.id}
                        size="small"
                        pagination={false}
                    />
                </div>
            )}
        </>
    )
}
