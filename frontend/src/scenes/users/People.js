import React, { useEffect, useState, useMemo } from 'react'
import { useValues, useActions } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { Cohort } from './Cohort'
import { PeopleTable } from './PeopleTable'
import { Button, Tabs, Input } from 'antd'
import { ExportOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import { hot } from 'react-hot-loader/root'
import { PageHeader } from 'lib/components/PageHeader'

const { TabPane } = Tabs
const ALLOWED_CATEGORIES = ['all', 'identified', 'anonymous']

export const People = hot(_People)
function _People() {
    const [isLoading, setIsLoading] = useState(true)
    const [people, setPeople] = useState(null)
    const [search, setSearch] = useState('')
    const [pagination, setPagination] = useState({
        all: {},
        identified: {},
        anonymous: {},
    })
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
        if (!ALLOWED_CATEGORIES.includes(categoryRaw)) push('/persons', { category, cohort: cohortId })
    }, [categoryRaw])

    const exampleEmail =
        (people && people.find((person) => person?.properties?.email)?.properties?.email) || 'example@gmail.com'

    return (
        <div>
            <PageHeader title="Persons" />
            <Cohort
                onChange={(cohortId) => {
                    push('/persons', { category, cohort: cohortId })
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
            <div className="mb">
                <Input
                    data-attr="persons-search"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && fetchPeople()}
                    placeholder={people && 'Try ' + exampleEmail + ' or has:email'}
                    style={{ maxWidth: 400 }}
                />
            </div>
            <Tabs
                defaultActiveKey={category}
                onChange={(category) => {
                    push('/persons', { category, cohort: cohortId })
                    fetchPeople(undefined, undefined, category)
                }}
            >
                <TabPane tab={<span data-attr="people-types-tab">All</span>} key="all" data-attr="people-types-tab" />
                <TabPane
                    tab={<span data-attr="people-types-tab">Identified</span>}
                    key="identified"
                    data-attr="people-types-tab"
                />
                <TabPane
                    tab={<span data-attr="people-types-tab">Anonymous</span>}
                    key="anonymous"
                    data-attr="people-types-tab"
                />
            </Tabs>

            <div>
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
        </div>
    )
}
