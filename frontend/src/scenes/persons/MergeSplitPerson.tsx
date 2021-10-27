import React from 'react'
import { Select, Row, Col, Radio, Modal } from 'antd'
import { PersonType } from '~/types'
import { useActions, useValues, BindLogic } from 'kea'
import './MergeSplitPerson.scss'
import { ActivityType, mergeSplitPersonLogic } from './mergeSplitPersonLogic'
import { capitalizeFirstLetter, midEllipsis, pluralize } from 'lib/utils'
import { ErrorMessage } from 'lib/components/ErrorMessage/ErrorMessage'
import { Tooltip } from 'lib/components/Tooltip'

export function MergeSplitPerson({ person }: { person: PersonType }): JSX.Element {
    const logicProps = { person }
    const { activity, executedLoading } = useValues(mergeSplitPersonLogic(logicProps))
    const { setActivity, execute, cancel } = useActions(mergeSplitPersonLogic(logicProps))

    return (
        <Modal
            visible
            title="Merge/split persons"
            onCancel={cancel}
            className="merge-split-person"
            okText={`${capitalizeFirstLetter(activity)} persons`}
            onOk={execute}
            okButtonProps={{ loading: executedLoading }}
            cancelButtonProps={{ disabled: executedLoading }}
        >
            <div className="activity-header">
                <Row align="middle">
                    <Radio.Group onChange={(e) => setActivity(e.target.value as ActivityType)} value={activity}>
                        <Col className="tab-btn ant-btn">
                            <Radio value="merge">Merge</Radio>
                        </Col>
                        <Col className="tab-btn ant-btn">
                            <Radio value="split" disabled={person.distinct_ids.length < 2}>
                                {person.distinct_ids.length < 2 ? (
                                    <Tooltip
                                        title="Only persons with more than two distinct IDs can be split."
                                        delayMs={0}
                                    >
                                        Split
                                    </Tooltip>
                                ) : (
                                    <>Split</>
                                )}
                            </Radio>
                        </Col>
                    </Radio.Group>
                </Row>
            </div>
            <BindLogic logic={mergeSplitPersonLogic} props={logicProps}>
                <>{activity === ActivityType.MERGE ? <MergePerson /> : <SplitPerson />}</>
            </BindLogic>
        </Modal>
    )
}

function MergePerson(): JSX.Element {
    const { persons, person, executedLoading } = useValues(mergeSplitPersonLogic)
    const { setListFilters, setSelectedPersonsToMerge } = useActions(mergeSplitPersonLogic)

    return (
        <>
            <p className="mb">
                Merge all properties and events of the selected persons into <strong>{person.name}</strong>{' '}
                <span style={{ fontSize: '1.2em' }}>(</span>
                <code title={person.distinct_ids[0]}>{midEllipsis(person.distinct_ids[0], 20)}</code>
                <span style={{ fontSize: '1.2em' }}>)</span>. If there is a <b>conflict</b>, the properties of{' '}
                <b>this person will take precedence</b>.
            </p>
            <Select
                mode="multiple"
                allowClear
                showSearch
                style={{ width: '100%' }}
                placeholder="Please select persons to merge"
                onChange={(value: number[]) => setSelectedPersonsToMerge(value)}
                filterOption={false}
                onSearch={(value) => {
                    setListFilters({ search: value })
                }}
                className="mt"
                disabled={executedLoading}
            >
                {persons.results &&
                    persons.results
                        .filter((p: PersonType) => p.uuid !== person.uuid)
                        .map((p: PersonType) =>
                            p.id ? (
                                <Select.Option value={p.id} key={p.id}>
                                    {p.name}
                                </Select.Option>
                            ) : undefined
                        )}
            </Select>
            <ErrorMessage style={{ marginTop: 16 }}>
                This action is not reversible. Please be sure before continuing.
            </ErrorMessage>
        </>
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
            <ErrorMessage style={{ marginTop: 16 }}>
                <div>
                    This will create <strong>{person.distinct_ids.length - 1}</strong> new{' '}
                    {pluralize(person.distinct_ids.length, 'person', undefined, false)}. This might change the numbers
                    in your charts, even historically. Please be certain.
                </div>
            </ErrorMessage>
        </>
    )
}
