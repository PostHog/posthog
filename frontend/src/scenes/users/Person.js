import React, { useEffect, useState } from 'react'
import { Events } from '../events/Events'
import api from 'lib/api'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { deletePersonData } from 'lib/utils'
import { Button } from 'antd'
import { hot } from 'react-hot-loader/root'

export const Person = hot(_Person)
function _Person({ _: distinctId, id }) {
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
            <h1 className="page-header">{person.name}</h1>
            <div style={{ maxWidth: 750 }}>
                <PropertiesTable
                    properties={{
                        ...person.properties,
                        distinct_id: person.distinct_ids,
                    }}
                />
                <small>
                    <a
                        href="https://posthog.com/docs/integrations/js-integration#identifying-users"
                        target="_blank"
                        rel="noopener noreferrer"
                    >
                        See documentation
                    </a>{' '}
                    on how to add properties to users using libraries.
                </small>
                <br />
                <br />
            </div>
            <Events fixedFilters={{ person_id: person.id }} />
        </div>
    ) : null
}
