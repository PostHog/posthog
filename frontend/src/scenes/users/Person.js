import React, { useEffect, useState } from 'react'
import { Events } from '../events/Events'
import api from 'lib/api'
import { PersonTable } from './PersonTable'
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

    function _handleChange(event) {
        var tag = event.target.getAttribute('tag')
        var newState = {}
        if (tag == 'first' || tag == 'last') {
            newState = {
                ...person,
                properties: {
                    ...person.properties,
                    name: {
                        ...person.properties.name,
                        [tag]: event.target.value || '',
                    },
                },
            }
        } else {
            newState = {
                ...person,
                properties: {
                    ...person.properties,
                    [tag]: event.target.value || '',
                },
            }
        }
        setPerson(newState)
    }

    return person ? (
        <div>
            <Button
                className="float-right"
                danger
                onClick={() => deletePersonData(person, () => history.push('/people'))}
            >
                Delete all data on this person
            </Button>
            <h1 className="page-header">
                {person.properties.name.first} {person.properties.name.last}
            </h1>
            <Button className="float-right">Save Person's Data</Button>

            <div style={{ maxWidth: 750 }}>
                <PersonTable
                    properties={{
                        props: { ...person.properties },
                        distinct_id: person.distinct_ids,
                        onChange: { _handleChange },
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
