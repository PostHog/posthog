import React, { useEffect, useState } from 'react'
import api from 'lib/api'
import { Button, Select } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import { PersonType } from '~/types'
import { useActions, useValues } from 'kea'
import { personsLogic } from './personsLogic'
import { toast } from 'react-toastify'
import posthog from 'posthog-js'

export function MergePersonButton({
    person,
    onPersonChange,
}: {
    person: PersonType
    onPersonChange: CallableFunction
}): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)
    const [selectedPeople, setSelectedPeople] = useState([])

    const { loadPersons, setListFilters } = useActions(personsLogic)
    const { persons } = useValues(personsLogic)
    useEffect(() => {
        loadPersons()
    }, [])

    useEffect(() => {
        loadPersons()
    }, [person.distinct_ids, person.id])
    return (
        <>
            {isModalOpen && (
                <Modal
                    visible
                    title={'Merge ' + person.name}
                    onCancel={() => setIsModalOpen(false)}
                    onOk={async () => {
                        const newPerson = await api.create('api/person/' + person.id + '/merge/', {
                            ids: selectedPeople,
                        })
                        if (newPerson.id) {
                            toast('People succesfully merged into one.')
                            posthog.capture('merge person completed')
                            setIsModalOpen(false)
                            onPersonChange(newPerson)
                        }
                    }}
                >
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
                                    <Select.Option value={person.id} key={persons.id}>
                                        {person.name}
                                    </Select.Option>
                                ))}
                    </Select>
                </Modal>
            )}
            <Button
                onClick={() => {
                    posthog.capture('merge person modal opened')
                    setIsModalOpen(true)
                }}
                className="float-right"
                style={{ marginRight: '10px' }}
            >
                Merge person
            </Button>
        </>
    )
}
