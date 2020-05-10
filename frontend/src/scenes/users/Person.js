import React, { useEffect, useState } from 'react'
import { EventsTable } from '../events/EventsTable'
import api from 'lib/api'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { deletePersonData } from 'lib/utils'
import { Button } from 'antd'

export function Person({ distinctId, id }) {
    const [person, setPerson] = useState(null)

    useEffect(() => {
        let url = ''
        if (distinctId) {
            url = `api/person/by_distinct_id/?distinct_id=${distinctId}`
        } else {
            url = `api/person/${id}`
        }
        api.get(url).then(setPerson)
    }, [distinctId, id])

    return person ? (
        <div>
            <Button
                className="float-right"
                danger
                onClick={() => deletePersonData(person, () => history.push('/people'))}
            >
                Delete all data on this person
            </Button>
            <h1>{person.name}</h1>
            <div style={{ maxWidth: 750 }}>
                <PropertiesTable properties={person.properties} />
                <table className="table">
                    <tbody>
                        <tr>
                            <td>Distinct IDs</td>
                            <td>
                                {person.distinct_ids.map(distinct_id => (
                                    <pre style={{ margin: 0 }} key={distinct_id}>
                                        {distinct_id}
                                    </pre>
                                ))}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
            <EventsTable fixedFilters={{ person_id: person.id }} />
        </div>
    ) : null
}
