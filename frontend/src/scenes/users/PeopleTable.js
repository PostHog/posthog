import React, { useState } from 'react'
import { Loading } from 'lib/utils'
import { Link } from 'react-router-dom'
import moment from 'moment'

function FilterLink({ property, value, onClick }) {
    const label = typeof value === 'object' ? JSON.stringify(value) : value

    if (onClick) {
        return (
            <a
                href="#"
                onClick={e => {
                    e.preventDefault()
                    onClick(property, value)
                }}
            >
                {label}
            </a>
        )
    } else {
        return <span>{label}</span>
    }
}

export function PeopleTable({ loading, people, onClickProperty }) {
    const [personSelected, setPersonSelected] = useState(null)

    return (
        <table className="table" style={{ position: 'relative', minHeight: loading ? 140 : 0 }}>
            {loading ? (
                <tbody>
                    <tr>
                        <td>
                            <Loading />
                        </td>
                    </tr>
                </tbody>
            ) : (
                <tbody>
                    <tr>
                        <th />
                        <th>Person</th>
                        <th>Last seen</th>
                    </tr>
                    {people && people.length === 0 && (
                        <tr>
                            <td colSpan={3}>
                                We haven't seen any data yet. If you haven't integrated PostHog,{' '}
                                <Link to="/setup">click here to set PostHog up on your app</Link>
                            </td>
                        </tr>
                    )}
                    {people &&
                        people.map(person => [
                            <tr
                                key={person.id}
                                className="cursor-pointer"
                                onClick={() => setPersonSelected(person.id === personSelected ? null : person.id)}
                            >
                                <td>
                                    <i className={`fi flaticon-zoom-${person.id === personSelected ? 'out' : 'in'}`} />
                                </td>
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
                                    <td />
                                    <td colSpan={2}>
                                        {Object.keys(person.properties).length === 0 &&
                                            'This person has no properties.'}
                                        <div className="d-flex flex-wrap flex-column" style={{ maxHeight: 200 }}>
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
                                                            onClick={onClickProperty}
                                                        />
                                                    </div>
                                                ))}
                                        </div>
                                    </td>
                                </tr>
                            ),
                        ])}
                </tbody>
            )}
        </table>
    )
}
