import React from 'react'
import { Select, Row, Col, Radio, Modal } from 'antd'
import { PersonType } from '~/types'
import { useActions, useValues, BindLogic } from 'kea'
import './MergeSplitPerson.scss'
import { ActivityType, mergeSplitPersonLogic } from './mergeSplitPersonLogic'
import { capitalizeFirstLetter, midEllipsis } from 'lib/utils'
import { ErrorMessage } from 'lib/components/ErrorMessage/ErrorMessage'

export function MergeSplitPerson({ person }: { person: PersonType }): JSX.Element {
    const logicProps = { person }
    const { activity } = useValues(mergeSplitPersonLogic(logicProps))
    const { setActivity, execute, cancel } = useActions(mergeSplitPersonLogic(logicProps))

    return (
        <Modal
            visible
            title="Merge/split persons"
            onCancel={cancel}
            className="merge-split-person"
            okText={`${capitalizeFirstLetter(activity)} persons`}
            onOk={execute}
        >
            <div className="activity-header">
                <Row align="middle">
                    <Radio.Group onChange={(e) => setActivity(e.target.value as ActivityType)} value={activity}>
                        <Col className="tab-btn ant-btn">
                            <Radio value="merge">Merge</Radio>
                        </Col>
                        <Col className="tab-btn ant-btn">
                            <Radio value="split"> Split</Radio>
                        </Col>
                    </Radio.Group>
                </Row>
            </div>
            <BindLogic logic={mergeSplitPersonLogic} props={logicProps}>
                <>{activity === ActivityType.MERGE ? <MergePerson /> : null}</>
            </BindLogic>

            <ErrorMessage style={{ marginTop: 16 }}>
                This action is not reversible. Please be sure before continuing.
            </ErrorMessage>
        </Modal>
    )
}

function MergePerson(): JSX.Element {
    const { persons, person } = useValues(mergeSplitPersonLogic)
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
            >
                {persons.results &&
                    persons.results
                        .filter((p) => p.uuid !== person.uuid)
                        .map((p) =>
                            p.id ? (
                                <Select.Option value={p.id} key={p.id}>
                                    {p.name}
                                </Select.Option>
                            ) : undefined
                        )}
            </Select>
        </>
    )
}
