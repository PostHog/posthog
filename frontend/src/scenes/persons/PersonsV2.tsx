import React, { useState, useEffect } from 'react'
import { useValues, useActions } from 'kea'
import { Cohort } from './Cohort'
import { PersonsTable } from './PersonsTableV2'
import { Button, Input, Row, Radio } from 'antd'
import { ExportOutlined, PlusOutlined } from '@ant-design/icons'
import { PageHeader } from 'lib/components/PageHeader'
import { personsLogic } from './personsLogic'
import { Link } from 'lib/components/Link'

export function PersonsV2(): JSX.Element {
    const { loadPersons, setListFilters } = useActions(personsLogic)
    const { persons, listFilters, personsLoading, exampleEmail } = useValues(personsLogic)
    const [searchTerm, setSearchTerm] = useState('') // Not on Kea because it's a component-specific store & to avoid changing the URL on every keystroke

    useEffect(() => {
        setSearchTerm(listFilters.search)
    }, [])

    return (
        <div>
            <PageHeader title="Persons" />
            <Cohort
                onChange={(cohort: string) => {
                    setListFilters({ cohort })
                }}
            />
            <Row style={{ gap: '0.75rem' }} className="mb">
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
                    style={{ maxWidth: 600, width: 'initial', flexGrow: 1 }}
                />
                <div>
                    <Radio.Group
                        buttonStyle="solid"
                        onChange={(e) => {
                            const key = e.target.value
                            console.log(key)
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
                <Button
                    type="default"
                    icon={<ExportOutlined />}
                    href={'/api/person.csv' + (listFilters.cohort ? '?cohort=' + listFilters.cohort : '')}
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
                />
            </div>
        </div>
    )
}
