import React, { useState, useEffect } from 'react'
import { useValues, useActions } from 'kea'
import { Cohort } from './Cohort'
import { PersonsTable } from './PersonsTableV2'
import { Button, Input, Row, Radio } from 'antd'
import { ExportOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import { PageHeader } from 'lib/components/PageHeader'
import { personsLogic } from './personsLogic'

export function PersonsV2(): JSX.Element {
    const { loadPersons, setListFilters } = useActions(personsLogic)
    const { persons, listFilters, personsLoading } = useValues(personsLogic)
    const [searchTerm, setSearchTerm] = useState('') // Not on Kea because it's a component-specific store & to avoid changing the URL on every keystroke

    const exampleEmail =
        (persons && persons.results.find((person) => person.properties?.email)?.properties?.email) ||
        'example@gmail.com'

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
                    placeholder={persons && 'Try ' + exampleEmail + ' or has:email'}
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
                    style={{ maxWidth: 400, width: 'initial', flexGrow: 1 }}
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
            </div>

            <div>
                <PersonsTable people={persons.results} loading={personsLoading} />

                <div style={{ margin: '3rem auto 10rem', width: 200 }}>
                    <Button type="link" disabled={!persons.previous} onClick={() => loadPersons(persons.previous)}>
                        <LeftOutlined style={{ verticalAlign: 'initial' }} /> Previous
                    </Button>
                    <Button type="link" disabled={!persons.next} onClick={() => loadPersons(persons.next)}>
                        Next <RightOutlined style={{ verticalAlign: 'initial' }} />
                    </Button>
                </div>
            </div>
        </div>
    )
}
