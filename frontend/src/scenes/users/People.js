import React, { useEffect, useState } from 'react'
import api from 'lib/api'
import { fromParams } from 'lib/utils'
import { Cohort } from './Cohort'
import { PeopleTable } from './PeopleTable'

import { Button } from 'antd'
import { ExportOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import { hot } from 'react-hot-loader/root'

export const People = hot(_People)
function _People() {
    const [loading, setLoading] = useState(true)
    const [people, setPeople] = useState(null)
    const [search, setSearch] = useState('')
    const [cohortId, setCohortId] = useState(fromParams()['cohort'])
    const [pagination, setPagination] = useState({})

    function fetchPeople({ url, scrollTop, search }) {
        setLoading(true)
        if (scrollTop)
            document.querySelector('section.ant-layout > .content').parentNode.scrollTo({ top: 0, behavior: 'smooth' })
        api.get(
            url ? url : `api/person/?${search ? 'search=' + search : ''}${cohortId ? '&cohort=' + cohortId : ''}`
        ).then(data => {
            setPeople(data.results)
            setLoading(false)
            setPagination({ next: data.next, previous: data.previous })
        })
    }

    useEffect(() => {
        fetchPeople({})
    }, [cohortId])

    const exampleEmail =
        (people && people.map(person => person.properties.email).filter(d => d)[0]) || 'example@gmail.com'

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
                onChange={e => setSearch(e.target.value)}
                onKeyDown={e => e.keyCode === 13 && fetchPeople({ search })}
                placeholder={people && 'Try ' + exampleEmail + ' or has:email'}
                style={{ maxWidth: 400 }}
            />
            <br />
            <PeopleTable people={people} loading={loading} actions={true} onChange={() => fetchPeople({ search })} />

            <div style={{ margin: '3rem auto 10rem', width: 200 }}>
                <Button
                    type="link"
                    disabled={!pagination.previous}
                    onClick={() => fetchPeople({ url: pagination.previous, scrollTop: true })}
                >
                    <LeftOutlined style={{ verticalAlign: 'initial' }} /> Previous
                </Button>
                <Button
                    type="link"
                    disabled={!pagination.next}
                    onClick={() => fetchPeople({ url: pagination.next, scrollTop: true })}
                >
                    Next <RightOutlined style={{ verticalAlign: 'initial' }} />
                </Button>
            </div>
        </div>
    )
}
