import React, { useEffect, useState, useMemo } from 'react'
import { useValues, useActions } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { Cohort } from './Cohort'
import { PeopleTable } from './PeopleTable'

import { Button, Tabs } from 'antd'
import { ExportOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import { hot } from 'react-hot-loader/root'

const { TabPane } = Tabs
const INITIAL_PAGINATION_STATE = {
    all: {},
    identified: {},
    anonymous: {},
}
const ALLOWED_CATEGORIES = ['all', 'identified', 'anonymous']

export const People = hot(_People)
function _People() {
    const [isLoading, setIsLoading] = useState(true)
    const [people, setPeople] = useState(null)
    const [search, setSearch] = useState('')
    // unfortunately – as this is JS – JSON is the best solution for deep copying initial state here
    const [pagination, setPagination] = useState(JSON.parse(JSON.stringify(INITIAL_PAGINATION_STATE)))
    const { push } = useActions(router)
    const {
        searchParams: { category: categoryRaw = 'all', cohort: cohortId },
    } = useValues(router)

    // ensure that there's no invalid category error
    const category = useMemo(() => (ALLOWED_CATEGORIES.includes(categoryRaw) ? categoryRaw : 'all'), categoryRaw)

    function fetchPeople(url, scrollTop, categoryOverride) {
        setIsLoading(true)
        let categoryLocal = categoryOverride || category
        if (scrollTop)
            document.querySelector('section.ant-layout > .content').parentNode.scrollTo({ top: 0, behavior: 'smooth' })
        if (!url) {
            url = 'api/person/'
            const query_params = [`category=${categoryLocal}`]
            if (search) query_params.push(`search=${search}`)
            if (cohortId) query_params.push(`cohort=${cohortId}`)
            if (query_params.length) url += `?${query_params.join('&')}`
        }
        api.get(url)
            .then((data) => {
                let newPagination = { ...pagination }
                newPagination[categoryLocal].next = data.next
                newPagination[categoryLocal].previous = data.previous
                setPagination(newPagination)
                setPeople(data.results)
            })
            .finally(() => {
                setIsLoading(false)
            })
    }

    function tabHasPagination(direction) {
        return direction === 'next' ? pagination[category].next : pagination[category].previous
    }

    useEffect(() => {
        fetchPeople()
    }, [cohortId])

    useEffect(() => {
        if (!ALLOWED_CATEGORIES.includes(categoryRaw)) push('/people', { category, cohort: cohortId })
    }, [categoryRaw])

    const exampleEmail =
        (people && people.find((person) => person?.properties?.email)?.properties?.email) || 'example@gmail.com'

    return (
        <div>
            <h1 className="page-header">Users</h1>
            <Cohort
                onChange={(cohortId) => {
                    push('/people', { category, cohort: cohortId })
                }}
            />
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
                onKeyDown={(e) => e.keyCode === 13 && fetchPeople()}
                placeholder={people && 'Try ' + exampleEmail + ' or has:email'}
                style={{ maxWidth: 400 }}
            />
            <br />
            <Tabs
                defaultActiveKey={category}
                onChange={(category) => {
                    push('/people', { category, cohort: cohortId })
                    fetchPeople(undefined, undefined, category)
                }}
                type="card"
            >
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
            <PeopleTable people={people} loading={isLoading} actions={true} onChange={() => fetchPeople()} />

            <div style={{ margin: '3rem auto 10rem', width: 200 }}>
                <Button
                    type="link"
                    disabled={!tabHasPagination('previous')}
                    onClick={() => fetchPeople(pagination[category].previous, true)}
                >
                    <LeftOutlined style={{ verticalAlign: 'initial' }} /> Previous
                </Button>
                <Button
                    type="link"
                    disabled={!tabHasPagination('next')}
                    onClick={() => fetchPeople(pagination[category].next, true)}
                >
                    Next <RightOutlined style={{ verticalAlign: 'initial' }} />
                </Button>
            </div>
        </div>
    )
}
