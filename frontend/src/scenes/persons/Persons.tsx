import React, { useState, useEffect } from 'react'
import { useValues, useActions } from 'kea'
import { PersonsTable } from './PersonsTable'
import { Button, Tabs, Input, Row } from 'antd'
import { ExportOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import { hot } from 'react-hot-loader/root'
import { PageHeader } from 'lib/components/PageHeader'
import { personsLogic } from './personsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PersonsV2 } from './PersonsV2'
import { CohortType } from '~/types'

const { TabPane } = Tabs

export const Persons = hot(_Persons)
function _Persons({ cohort }: { cohort: CohortType }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags['persons-2353'] ? <PersonsV2 cohort={cohort} /> : <PersonsV1 cohort={cohort} />
}

function PersonsV1({ cohort }: { cohort: CohortType }): JSX.Element {
    const { loadPersons, setListFilters } = useActions(personsLogic)
    const { persons, listFilters, personsLoading } = useValues(personsLogic)
    const [searchTerm, setSearchTerm] = useState('') // Not on Kea because it's a component-specific store & to avoid changing the URL on every keystroke

    const exampleEmail =
        (persons && persons.results.find((person) => person.properties?.email)?.properties?.email) ||
        'example@gmail.com'

    useEffect(() => {
        setSearchTerm(listFilters.search)
        if (cohort) {
            setListFilters({ cohort: cohort.id })
        }

        loadPersons()
    }, [])

    return (
        <div>
            {!cohort && <PageHeader title="Persons" />}
            <Row style={{ justifyContent: 'space-between', gap: '0.75rem' }} className="mb">
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

                <Button
                    type="default"
                    icon={<ExportOutlined />}
                    href={'/api/person.csv' + (listFilters.cohort ? '?cohort=' + listFilters.cohort : '')}
                >
                    Export
                </Button>
            </Row>
            <Tabs
                activeKey={listFilters.is_identified !== undefined ? listFilters.is_identified.toString() : 'default'}
                onChange={(key) => {
                    setListFilters({ is_identified: key === 'default' ? undefined : key })
                    loadPersons()
                }}
            >
                <TabPane
                    tab={<span data-attr="people-types-tab">All</span>}
                    key="default"
                    data-attr="people-types-tab"
                />
                <TabPane
                    tab={<span data-attr="people-types-tab">Identified</span>}
                    key="true"
                    data-attr="people-types-tab"
                />
                <TabPane
                    tab={<span data-attr="people-types-tab">Anonymous</span>}
                    key="false"
                    data-attr="people-types-tab"
                />
            </Tabs>

            <div>
                <PersonsTable
                    people={persons.results}
                    loading={personsLoading}
                    actions={true}
                    cohort={cohort}
                    onChange={() => loadPersons()}
                />

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
