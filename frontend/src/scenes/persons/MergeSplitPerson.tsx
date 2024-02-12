import './MergeSplitPerson.scss'

import { Modal, Select } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { pluralize } from 'lib/utils'

import { PersonType } from '~/types'

import { mergeSplitPersonLogic } from './mergeSplitPersonLogic'

export function MergeSplitPerson({ person }: { person: PersonType }): JSX.Element {
    const logicProps = { person }
    const { executedLoading } = useValues(mergeSplitPersonLogic(logicProps))
    const { execute, cancel } = useActions(mergeSplitPersonLogic(logicProps))

    return (
        <Modal
            visible
            title="Split persons"
            onCancel={cancel}
            className="merge-split-person"
            okText="Split persons"
            onOk={execute}
            okButtonProps={{ loading: executedLoading }}
            cancelButtonProps={{ disabled: executedLoading }}
        >
            {person.distinct_ids.length < 2 ? (
                'Only persons with more than two distinct IDs can be split.'
            ) : (
                <BindLogic logic={mergeSplitPersonLogic} props={logicProps}>
                    <>
                        <SplitPerson />
                    </>
                </BindLogic>
            )}
        </Modal>
    )
}

function SplitPerson(): JSX.Element | null {
    const { person, executedLoading } = useValues(mergeSplitPersonLogic)
    const { setSelectedPersonToAssignSplit } = useActions(mergeSplitPersonLogic)

    if (!person) {
        return null
    }

    return (
        <>
            <p>This will split all Distinct IDs for this person into unique persons.</p>
            <p>
                You can select a distinct ID for which all the current properties will be assigned (<i>optional</i>).
                All other new users will start without any properties.
            </p>
            <Select
                allowClear
                showSearch
                style={{ width: '100%' }}
                placeholder="Select a distinct ID to which to assign all properties (optional)"
                onChange={(value) => setSelectedPersonToAssignSplit(value as string)}
                filterOption={false}
                disabled={executedLoading}
            >
                {person?.distinct_ids.map((distinct_id) => (
                    <Select.Option value={distinct_id} key={distinct_id}>
                        {distinct_id}
                    </Select.Option>
                ))}
            </Select>
            <LemonBanner type="warning" className="mt-4">
                This will create <strong>{person.distinct_ids.length - 1}</strong>{' '}
                {pluralize(person.distinct_ids.length - 1, 'new person', undefined, false)}. This might change the
                numbers in your charts, even historically. Please be certain.
            </LemonBanner>
        </>
    )
}
