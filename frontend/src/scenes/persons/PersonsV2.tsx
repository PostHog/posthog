import React, { useState, useEffect } from 'react'
import { useValues, useActions } from 'kea'
import { PersonsTable } from './PersonsTable'
import { Button, Input, Row, Radio } from 'antd'
import { ExportOutlined, PlusOutlined } from '@ant-design/icons'
import { PageHeader } from 'lib/components/PageHeader'
import { personsLogic } from './personsLogic'
import { Link } from 'lib/components/Link'
import { CohortType } from '~/types'
import { LinkButton } from 'lib/components/LinkButton'
import { ClockCircleFilled } from '@ant-design/icons'
import { toParams } from 'lib/utils'

export function PersonsV2({ cohort }: { cohort: CohortType }): JSX.Element {
    const { loadPersons, setListFilters } = useActions(personsLogic)
    const { persons, listFilters, personsLoading, exampleEmail } = useValues(personsLogic)
    const [searchTerm, setSearchTerm] = useState('') // Not on Kea because it's a component-specific store & to avoid changing the URL on every keystroke

    useEffect(() => {
        setSearchTerm(listFilters.search)
        if (cohort) {
            setListFilters({ cohort: cohort.id })
            loadPersons()
        }
    }, [])

    return (
        <div>
            {!cohort && <PageHeader title="Persons" />}
            <Row style={{ gap: '0.75rem' }} className="mb">
                <div style={{ flexGrow: 1, maxWidth: 600 }}>
                    <Input.Search
                        data-attr="persons-search"
                        placeholder={`search person by email, name or ID (e.g. ${exampleEmail})`}
                        autoFocus
                        value={searchTerm}
                        onChange={(e) => {
                            setSearchTerm(e.target.value)
                            if (!e.target.value) {
                                setListFilters({ search: undefined })
                                loadPersons()
                            }
                        }}
                        enterButton
                        allowClear
                        onSearch={() => {
                            setListFilters({ search: searchTerm || undefined })
                            loadPersons()
                        }}
                        style={{ width: '100%' }}
                    />
                    <div className="text-muted text-small">
                        You can also filter persons that have a certain property set (e.g. <code>has:email</code> or{' '}
                        <code>has:name</code>)
                    </div>
                </div>
                <div>
                    <Radio.Group
                        buttonStyle="solid"
                        onChange={(e) => {
                            const key = e.target.value
                            setListFilters({ is_identified: key === 'all' ? undefined : key })
                            loadPersons()
                        }}
                        value={listFilters.is_identified !== undefined ? listFilters.is_identified.toString() : 'all'}
                    >
                        <Radio.Button value="all">All users</Radio.Button>
                        <Radio.Button value="true">Identified</Radio.Button>
                        <Radio.Button value="false">Anonymous</Radio.Button>
                    </Radio.Group>
                </div>
            </Row>
            <div className="mb text-right">
                {cohort ? (
                    <LinkButton
                        to={`/sessions?${toParams({ properties: [{ key: 'id', value: cohort.id, type: 'cohort' }] })}`}
                        target="_blank"
                    >
                        <ClockCircleFilled /> View sessions
                    </LinkButton>
                ) : null}
                <Button
                    type="default"
                    icon={<ExportOutlined />}
                    href={'/api/person.csv' + (listFilters.cohort ? '?cohort=' + listFilters.cohort : '')}
                    style={{ marginLeft: 8 }}
                >
                    Export
                </Button>
                {/* TODO: Hidden until new cohorts UX is defined */}
                <Link to="/cohorts/new" style={{ display: 'none' }} className="ml">
                    <Button type="default" icon={<PlusOutlined />}>
                        New Cohort
                    </Button>
                </Link>
            </div>

            <div>
                <PersonsTable
                    people={persons.results}
                    loading={personsLoading}
                    hasPrevious={!!persons.previous}
                    hasNext={!!persons.next}
                    loadPrevious={() => loadPersons(persons.previous)}
                    loadNext={() => loadPersons(persons.next)}
                    allColumns
                    cohort={cohort}
                />
            </div>
        </div>
    )
}
