import React, { useEffect, useState } from 'react'
import api from 'lib/api'
import { Select } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import { PersonType } from '~/types'
import { useActions, useValues } from 'kea'
import { personsLogic } from './personsLogic'
import { toast } from 'react-toastify'
import posthog from 'posthog-js'

export function MergePerson({
    person,
    onPersonChange,
    closeModal,
}: {
    person: PersonType
    onPersonChange: CallableFunction
    closeModal: () => void
}): JSX.Element {
    const [selectedPeople, setSelectedPeople] = useState([])

    const { loadPersons, setListFilters } = useActions(personsLogic)
    const { persons } = useValues(personsLogic)
    useEffect(() => {
        loadPersons()
    }, [person.distinct_ids, person.id])
    return (
        <Modal
            visible
            title={'Merge ' + person.name}
            onCancel={closeModal}
            onOk={async () => {
                const newPerson = await api.create('api/person/' + person.id + '/merge/', {
                    ids: selectedPeople,
                })
                if (newPerson.id) {
                    toast('Persons succesfully merged.')
                    posthog.capture('merge person completed', { merge_count: selectedPeople.length })
                    closeModal()
                    onPersonChange(newPerson)
                }
            }}
        >
            Merge all properties and events of the selected users into <strong>{person.name}.</strong>
            <br />
            <br />
            Note: If there is a conflict, the properties of <strong>{person.name}</strong> will take precedence.
            <br />
            <br />
            <Select
                mode="multiple"
                allowClear
                showSearch
                style={{ width: '100%' }}
                placeholder="Please select people to merge"
                onChange={(value) => setSelectedPeople(value)}
                filterOption={false}
                onSearch={(value) => {
                    setListFilters({ search: value })
                    loadPersons()
                }}
            >
                {persons.results &&
                    persons.results
                        .filter((p) => p.uuid !== person.uuid)
                        .map((person) => (
                            <Select.Option value={person.id} key={person.id}>
                                {person.name}
                            </Select.Option>
                        ))}
            </Select>
            <div className="mt text-danger">This action is not reversible. Please be sure before continuing.</div>
        </Modal>
    )
}
