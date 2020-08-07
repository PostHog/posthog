import React, { useEffect, useState } from 'react'
import api from 'lib/api'
import { fromParams } from 'lib/utils'
import { Cohort } from './Cohort'
import { PeopleTable } from './PeopleTable'

import { Button, Tabs } from 'antd'
import { ExportOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import { hot } from 'react-hot-loader/root'

const { TabPane } = Tabs
const defaultPaginationObj = {
    all: {},
    identified: {},
    anonymous: {},
}

export const People = hot(_People)
function _People() {
    const [loading, setLoading] = useState(true)
    const [people, setPeople] = useState(null)
    const [search, setSearch] = useState('')
    const [cohortId, setCohortId] = useState(fromParams()['cohort'])
    const [usersType, setUsersType] = useState('all')
    const [pagination, setPagination] = useState({ ...defaultPaginationObj })

    function fetchPeople({ url, scrollTop, selection }) {
        setLoading(true)
        let currentTab = selection ? selection : usersType
        if (selection) setUsersType(selection)
        if (scrollTop)
            document.querySelector('section.ant-layout > .content').parentNode.scrollTo({ top: 0, behavior: 'smooth' })
        if (!url) {
            url = 'api/person/'
            const query_params = []
            if (search) query_params.push(`search=${search}`)
            if (cohortId) query_params.push(`cohort=${cohortId}`)
            if (currentTab === 'identified' || currentTab === 'anonymous') query_params.push(`category=${currentTab}`)
            if (query_params.length) url += `?${query_params.join('&')}`
        }
        api.get(url).then((data) => {
            let newPagination = { ...pagination }
            newPagination[currentTab].next = data.next
            newPagination[currentTab].previous = data.previous
            setPagination(newPagination)
            setPeople(data.results)
            setLoading(false)
        })
    }

    function tabHasPagination(direction) {
        if (usersType === undefined) {
            return direction === 'next' ? pagination['all'].next : pagination['all'].previous
        }
        return direction === 'next' ? pagination[usersType].next : pagination[usersType].previous
    }

    useEffect(() => {
        fetchPeople({})
    }, [cohortId])

    const exampleEmail =
        (people && people.map((person) => person.properties.email).filter((d) => d)[0]) || 'example@gmail.com'

    return (
        <div>
            <h1 className="page-header">Users</h1>
            <Cohort onChange={setCohortId} />
            <Button
                type="default"
                icon={<ExportOutlined />}
                href={'/api/person.csv' + (cohortId ? '?cohort=' + cohortId : '')}
                style={{ marginBottom: '1rem' }}
            >
                Export
            </Button>
            <input
                className="form-control"
                name="search"
                autoFocus
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.keyCode === 13 && fetchPeople({})}
                placeholder={people && 'Try ' + exampleEmail + ' or has:email'}
                style={{ maxWidth: 400 }}
            />
            <br />
            <Tabs defaultActiveKey="all" onChange={(key) => fetchPeople({ selection: key })} type="card">
                <TabPane
                    tab={<span data-attr="people-types-tab">All Users</span>}
                    key="all"
                    data-attr="people-types-tab"
                ></TabPane>
                <TabPane
                    tab={<span data-attr="people-types-tab">Identified Users</span>}
                    key="identified"
                    data-attr="people-types-tab"
                ></TabPane>
                <TabPane
                    tab={<span data-attr="people-types-tab">Anonymous Users</span>}
                    key="anonymous"
                    data-attr="people-types-tab"
                ></TabPane>
            </Tabs>
            <PeopleTable people={people} loading={loading} actions={true} onChange={() => fetchPeople({})} />

            <div style={{ margin: '3rem auto 10rem', width: 200 }}>
                <Button
                    type="link"
                    disabled={!tabHasPagination('previous')}
                    onClick={() => fetchPeople({ url: pagination[usersType].previous, scrollTop: true })}
                >
                    <LeftOutlined style={{ verticalAlign: 'initial' }} /> Previous
                </Button>
                <Button
                    type="link"
                    disabled={!tabHasPagination('next')}
                    onClick={() => fetchPeople({ url: pagination[usersType].next, scrollTop: true })}
                >
                    Next <RightOutlined style={{ verticalAlign: 'initial' }} />
                </Button>
            </div>
        </div>
    )
}
