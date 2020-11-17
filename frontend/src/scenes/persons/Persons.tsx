import React from 'react'
import { useValues, useActions } from 'kea'
//import { Cohort } from './Cohort'
import { PersonsTable } from './PersonsTable'
import { Button, Tabs, Input } from 'antd'
import { ExportOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import { hot } from 'react-hot-loader/root'
import { PageHeader } from 'lib/components/PageHeader'
import { personsLogic } from './personsLogic'

const { TabPane } = Tabs

export const Persons = hot(_Persons)
function _Persons(): JSX.Element {
    const { loadPersons, setListFilters } = useActions(personsLogic)
    const { persons, listFilters, personsLoading } = useValues(personsLogic)
    const cohortId = null

    /*useEffect(() => {
        fetchPersons()
    }, [cohortId])

    useEffect(() => {
        if (!ALLOWED_CATEGORIES.includes(categoryRaw)) push('/persons', { category, cohort: cohortId })
    }, [categoryRaw])
*/
    const exampleEmail =
        (persons && persons.results.find((person) => person.properties?.email)?.properties?.email) ||
        'example@gmail.com'

    return (
        <div>
            <PageHeader title="Persons" />
            {/* <Cohort
                onChange={(cohortId) => {
                    push('/persons', { category, cohort: cohortId })
                }}
            /> */}
            <Button
                type="default"
                icon={<ExportOutlined />}
                href={'/api/person.csv' + (cohortId ? '?cohort=' + cohortId : '')}
                style={{ marginBottom: '1rem' }}
            >
                Export
            </Button>
            <div className="mb">
                <form
                    onSubmit={(e) => {
                        e.preventDefault()
                        loadPersons()
                    }}
                >
                    <Input
                        data-attr="persons-search"
                        value={listFilters.search}
                        onChange={(e) => setListFilters({ search: e.target.value })}
                        placeholder={persons && 'Try ' + exampleEmail + ' or has:email'}
                        style={{ maxWidth: 400 }}
                    />
                </form>
            </div>
            {JSON.stringify(listFilters)}
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
