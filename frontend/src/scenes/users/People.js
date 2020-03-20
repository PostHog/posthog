import React, { useEffect, useState } from 'react'
import api from 'lib/api'
import { fromParams } from 'lib/utils'
import { Cohort } from './Cohort'
import { PeopleTable } from './PeopleTable'

export function People({ history }) {
    const [loading, setLoading] = useState(true)
    const [people, setPeople] = useState(null)
    const [search, setSearch] = useState(undefined)
    const [hasNext, setHasNext] = useState(null)

    function fetchPeople(search, cohort_id) {
        if (search !== undefined) {
            setLoading(true)
        }

        api.get(
            `api/person/?include_last_event=1&${!!search ? 'search=' + search : ''}${
                cohort_id ? 'cohort=' + cohort_id : ''
            }`
        ).then(data => {
            // TODO: breakpoint if fetching when previous didn't finish
            setPeople(data.results)
            setHasNext(data.next)
            setLoading(false)
        })
    }

    function clickNext() {
        setLoading(true)
        setHasNext(null)

        api.get(hasNext).then(olderPeople => {
            setPeople([...people, ...olderPeople.results])
            setHasNext(olderPeople.next)
            setLoading(false)
        })
    }

    useEffect(() => {
        fetchPeople(undefined, fromParams()['cohort'])
    }, [])

    const exampleEmail =
        (people && people.map(person => person.properties.email).filter(d => d)[0]) || 'example@gmail.com'

    return (
        <div>
            <h1>Users</h1>
            <Cohort onChange={cohort_id => fetchPeople(false, cohort_id)} history={history} />
            {people && (
                <input
                    className="form-control"
                    name="search"
                    autoFocus
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    onKeyDown={e => e.keyCode === 13 && fetchPeople(search)}
                    placeholder={people && 'Try ' + exampleEmail + ' or has:email'}
                />
            )}
            <br />

            <PeopleTable
                loading={loading}
                people={people}
                onClickProperty={(property, value) => {
                    const newSearch = search ? `${search.trim()} ${value}` : value
                    setSearch(newSearch)
                    fetchPeople(newSearch)
                }}
            />

            {people && people.length > 0 && hasNext && (
                <button
                    className="btn btn-primary"
                    onClick={clickNext}
                    style={{ margin: '2rem auto 15rem', display: 'block' }}
                    disabled={!hasNext}
                >
                    Load more events
                </button>
            )}
        </div>
    )
}
