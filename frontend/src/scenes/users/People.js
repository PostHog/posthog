import React, { useEffect, useState } from 'react'
import api from 'lib/api'
import { Link } from 'react-router-dom'
import moment from 'moment'
import { fromParams, Loading, toParams } from 'lib/utils'
import { Cohort } from './Cohort'

function FilterLink({ value, onClick }) {
    return (
        <a
            href="#"
            onClick={e => {
                e.preventDefault()
                onClick && onClick(value)
            }}
        >
            {typeof value === 'object' ? JSON.stringify(value) : value}
        </a>
    )
}

export function People({ history }) {
    const [loading, setLoading] = useState(true)
    const [people, setPeople] = useState(null)
    const [search, setSearch] = useState(undefined)
    const [hasNext, setHasNext] = useState(null)
    const [personSelected, setPersonSelected] = useState(null)

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
            <table className="table" style={{ position: 'relative' }}>
                {loading && <Loading />}
                <tbody>
                    <tr>
                        <th>Person</th>
                        <th>Last seen</th>
                    </tr>
                    {people && people.length === 0 && (
                        <tr>
                            <td colSpan="2">
                                We haven't seen any data yet. If you haven't integrated PostHog,{' '}
                                <Link to="/setup">click here to set PostHog up on your app</Link>
                            </td>
                        </tr>
                    )}
                    {people &&
                        people.map(person => [
                            <tr key={person.id} className="cursor-pointer" onClick={() => setPersonSelected(person.id)}>
                                <td>
                                    <Link
                                        to={'/person/' + encodeURIComponent(person.distinct_ids[0])}
                                        className="ph-no-capture"
                                    >
                                        {person.name}
                                    </Link>
                                </td>
                                <td>{person.last_event && moment(person.last_event.timestamp).fromNow()}</td>
                            </tr>,
                            personSelected === person.id && (
                                <tr key={person.id + '_open'}>
                                    <td colSpan="4">
                                        {Object.keys(person.properties).length === 0 &&
                                            'This person has no properties.'}
                                        <div className="d-flex flex-wrap flex-column" style={{ height: 200 }}>
                                            {Object.keys(person.properties)
                                                .sort()
                                                .map(key => (
                                                    <div
                                                        style={{
                                                            flex: '0 1',
                                                        }}
                                                        key={key}
                                                    >
                                                        <strong>{key}:</strong>{' '}
                                                        <FilterLink
                                                            property={key}
                                                            value={person.properties[key]}
                                                            onClick={value => {
                                                                const newSearch = search
                                                                    ? `${search.trim()} ${value}`
                                                                    : value
                                                                setSearch(newSearch)
                                                                fetchPeople(newSearch)
                                                            }}
                                                        />
                                                    </div>
                                                ))}
                                        </div>
                                    </td>
                                </tr>
                            ),
                        ])}
                </tbody>
            </table>
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
