import React, { useEffect, useState } from 'react'
import { Events } from '../events/Events'
import api from 'lib/api'
import { PersonTable } from './PersonTable'
import { deletePersonData, savePersonData } from 'lib/utils'
import { Button, Modal } from 'antd'
import { CheckCircleTwoTone } from '@ant-design/icons'
import { hot } from 'react-hot-loader/root'
const confirm = Modal.confirm
export const Person = hot(_Person)
function _Person({ _: distinctId, id }) {
    const [person, setPerson] = useState(null)
    const [personChanged, setPersonChanged] = useState(false)
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
        setPersonChanged(true)
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

    function showConfirm(type, text) {
        confirm({
            centered: true,
            title: text,
            icon: <CheckCircleTwoTone twoToneColor="#52c41a" />,
            content: `Click OK to Save Person's Data`,
            okType: type === 'delete' ? 'danger' : 'primary',
            onOk() {
                savePersonData(person)
            },
            onCancel() {},
        })
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
            <Button
                className="float-right"
                onClick={() => showConfirm('save', "Save Person's Data?")}
                disabled={!personChanged}
            >
                Save Person's Data
            </Button>

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
