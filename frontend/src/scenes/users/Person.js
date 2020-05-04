import React, { useEffect, useState } from 'react'
import { EventsTable } from '../events/EventsTable'
import api from 'lib/api'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { toast } from 'react-toastify'
import { deletePersonData } from 'lib/utils'
import { Button } from 'antd'

export function Person({ match, history }) {
    const [person, setPerson] = useState(null)

    useEffect(() => {
        let url = ''
        if (match.params.distinct_id) {
            url = `api/person/by_distinct_id/?distinct_id=${match.params.distinct_id}`
        } else {
            url = `api/person/${match.params.id}`
        }
        api.get(url).then(setPerson)
    }, [match.params.distinct_id, match.params.id])

    return person ? (
        <div>
            <Button className="float-right" danger onClick={() => deletePersonData(person)}>
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
            <EventsTable fixedFilters={{ person_id: person.id }} history={history} />
        </div>
    ) : null
}
