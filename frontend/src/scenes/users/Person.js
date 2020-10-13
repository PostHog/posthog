import React, { useEffect, useState } from 'react'
import { Events } from '../events/Events'
import api from 'lib/api'
import { router } from 'kea-router'
import { PersonTable } from './PersonTable'
import { deletePersonData, savePersonData } from 'lib/utils'
import { changeType } from 'lib/utils/changeType'
import { Button, Modal, Tabs } from 'antd'
import { CheckCircleTwoTone, DeleteOutlined } from '@ant-design/icons'
import { hot } from 'react-hot-loader/root'
import { SessionsTable } from '../sessions/SessionsTable'

const { TabPane } = Tabs

const confirm = Modal.confirm
export const Person = hot(_Person)
function _Person({ _: distinctId, id }) {
    const { innerWidth } = window
    const isScreenSmall = innerWidth < 700
    const { push } = router.actions

    const [person, setPerson] = useState(null)
    const [personChanged, setPersonChanged] = useState(false)
    const [activeTab, setActiveTab] = useState('events')

    useEffect(() => {
        if (distinctId) {
            api.get(`api/person/?distinct_id=${distinctId}`).then((response) => {
                if (response.results.length > 0) {
                    setPerson(response.results[0])
                } else {
                    push('/404')
                }
            })
        } else {
            api.get(`api/person/${id}`).then(setPerson)
        }
    }, [distinctId, id])

    function _handleChange(event) {
        setPersonChanged(true)
        let tag, value
        let newState = {}
        if (typeof event.item != 'undefined') {
            tag = event.item.props.name
            value = event.key === 'true' ? true : false
        } else {
            tag = event.target.getAttribute('tag')
            value = event.target.value.length === 0 ? null : changeType(event.target.type, event.target.value)
        }
        if (tag == 'first' || tag == 'last') {
            newState = {
                ...person,
                properties: {
                    ...person.properties,
                    name: {
                        ...person.properties.name,
                        [tag]: value,
                    },
                },
            }
        } else {
            newState = {
                ...person,
                properties: {
                    ...person.properties,
                    [tag]: value,
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
            content: '',
            okType: 'primary',
            okText: 'Yes',
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
                {isScreenSmall ? <DeleteOutlined></DeleteOutlined> : 'Delete all data on this person'}
            </Button>
            <Button
                className="float-right"
                onClick={() => showConfirm('save', "Are you sure you want to update this person's properties?")}
                disabled={!personChanged}
                style={{ marginRight: '10px' }}
            >
                Save updated data
            </Button>
            <h1 className="page-header">
                {'name' in person.properties ? person.properties.name.first : person.name}{' '}
                {person.properties.name ? person.properties.name.last : ''}
            </h1>
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
            <Tabs
                defaultActiveKey={activeTab}
                onChange={(tab) => {
                    setActiveTab(tab)
                }}
            >
                <TabPane
                    tab={<span data-attr="people-types-tab">Events</span>}
                    key="events"
                    data-attr="people-types-tab"
                />
                {window.posthog?.isFeatureEnabled('session-recording-player') && (
                    <TabPane
                        tab={<span data-attr="people-types-tab">Sessions By Day</span>}
                        key="sessions"
                        data-attr="people-types-tab"
                    />
                )}
            </Tabs>
            {activeTab === 'events' ? (
                <Events isPersonPage={true} fixedFilters={{ person_id: person.id }} />
            ) : (
                <SessionsTable personIds={person.distinct_ids} isPersonPage={true} />
            )}
        </div>
    ) : null
}
