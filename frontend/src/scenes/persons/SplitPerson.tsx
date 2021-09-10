import React, { useState } from 'react'
import api from 'lib/api'
import { Select } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import { PersonType } from '~/types'
import { toast } from 'react-toastify'
import posthog from 'posthog-js'

export function SplitPerson({
    person,
    onPersonChange,
    closeModal,
}: {
    person: PersonType
    onPersonChange: CallableFunction
    closeModal: () => void
}): JSX.Element {
    const [selectedDistinctId, setSelectedDistinctId] = useState(false as false | string | number)

    return (
        <Modal
            visible
            title={'Merge ' + person.name}
            onCancel={closeModal}
            okText="Split person"
            onOk={async () => {
                const newPerson = await api.create('api/person/' + person.id + '/split/', {
                    ...(selectedDistinctId ? { main_distinct_id: selectedDistinctId } : {}),
                })
                if (newPerson.id) {
                    toast('Persons succesfully split.')
                    posthog.capture('split person completed', { merge_count: person.distinct_ids.length })
                    closeModal()
                    onPersonChange(newPerson)
                }
            }}
        >
            This will split all distinct id's into unique persons.
            <br />
            <br />
            You can select a distinct id that the current properties will be assigned to (optional). All other new users
            will start without any properties.
            <br />
            <br />
            <Select
                allowClear
                showSearch
                style={{ width: '100%' }}
                placeholder="Select a distinct id to assign all properties to (optional)"
                onChange={(value) => setSelectedDistinctId(value)}
                filterOption={false}
            >
                {person.distinct_ids.map((distinct_id) => (
                    <Select.Option value={distinct_id} key={distinct_id}>
                        {distinct_id}
                    </Select.Option>
                ))}
            </Select>
            <div className="mt text-danger">This action is not reversible. Please be sure before continuing.</div>
        </Modal>
    )
}
