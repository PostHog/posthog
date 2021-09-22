import React, { useState } from 'react'
import api from 'lib/api'
import { Select } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import { PersonType } from '~/types'
import { toast } from 'react-toastify'
import posthog from 'posthog-js'
import { router } from 'kea-router'

export function SplitPerson({ person, closeModal }: { person: PersonType; closeModal: () => void }): JSX.Element {
    const [selectedDistinctId, setSelectedDistinctId] = useState(false as false | string | number)
    const [isLoading, setIsLoading] = useState(false)

    return (
        <Modal
            visible
            title={'Split ' + person.name}
            onCancel={closeModal}
            okText="Split person"
            okButtonProps={{
                loading: isLoading,
            }}
            onOk={async () => {
                setIsLoading(true)
                const splitAction = await api.create('api/person/' + person.id + '/split/', {
                    ...(selectedDistinctId ? { main_distinct_id: selectedDistinctId } : {}),
                })
                setIsLoading(false)
                if (splitAction.success) {
                    toast(
                        'We are in the process of splitting this person. It may take up to a couple of minutes to complete.'
                    )
                    posthog.capture('split person started', { merge_count: person.distinct_ids.length })
                    closeModal()
                    router.actions.push('/persons')
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
                onChange={(value) => setSelectedDistinctId(value as string)}
                filterOption={false}
            >
                {person.distinct_ids.map((distinct_id) => (
                    <Select.Option value={distinct_id} key={distinct_id}>
                        {distinct_id}
                    </Select.Option>
                ))}
            </Select>
            <div className="mt text-danger">
                This will create <strong>{person.distinct_ids.length - 1}</strong> new person
                {person.distinct_ids.length - 1 != 1 && 's'}. This might change the numbers in your charts, even
                historically. Please be sure before continuing.
            </div>
        </Modal>
    )
}
