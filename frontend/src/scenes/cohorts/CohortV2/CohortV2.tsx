import React from 'react'
import { useActions, useValues } from 'kea'
import { CohortNameInput } from './CohortNameInput'
import { CohortDescriptionInput } from './CohortDescriptionInput'
import { CohortTypeSelector, DYNAMIC, STATIC } from './CohortTypeSelector'
import { Button, Col, Divider, Row } from 'antd'
import { CohortMatchingCriteriaSection } from './CohortMatchingCriteriaSection'
import { CohortGroupType, CohortType } from '~/types'
import { cohortLogic } from '../cohortLogic'
import { PROPERTY_MATCH_TYPE } from 'lib/constants'
import { InboxOutlined, DeleteOutlined, SaveOutlined } from '@ant-design/icons'
import Dragger from 'antd/lib/upload/Dragger'
import { CohortDetailsRow } from './CohortDetailsRow'
import { Persons } from 'scenes/persons/Persons'

export function CohortV2(props: { cohort: CohortType }): JSX.Element {
    const logic = cohortLogic(props)
    const { setCohort } = useActions(logic)
    const { cohort, lastSavedAt } = useValues(logic)

    const onNameChange = (name: string): void => {
        setCohort({
            ...cohort,
            name,
        })
    }

    const onDescriptionChange = (description: string): void => {
        setCohort({
            ...cohort,
            description,
        })
    }

    const onCriteriaChange = (_group: Partial<CohortGroupType>, id: string): void => {
        const index = cohort.groups.findIndex((group: CohortGroupType) => group.id === id)
        if (_group.matchType) {
            cohort.groups[index] = {
                id: cohort.groups[index].id,
                ..._group,
            }
        } else {
            cohort.groups[index] = {
                ...cohort.groups[index],
                ..._group,
            }
        }
        setCohort({ ...cohort })
    }

    const onAddGroup = (): void => {
        cohort.groups = [
            ...cohort.groups,
            {
                id: Math.random().toString().substr(2, 5),
                matchType: PROPERTY_MATCH_TYPE,
                properties: [],
            },
        ]
        setCohort({ ...cohort })
    }

    const onRemoveGroup = (index: number): void => {
        cohort.groups.splice(index, 1)
        setCohort({ ...cohort })
    }

    const onTypeChange = (type: string): void => {
        if (type === STATIC) {
            setCohort({
                ...cohort,
                is_static: true,
            })
        } else if (type === DYNAMIC) {
            setCohort({
                ...cohort,
                is_static: false,
            })
        }
    }

    const staticCSVDraggerProps = {
        name: 'file',
        multiple: false,
        fileList: cohort.csv ? [cohort.csv] : [],
        beforeUpload(file: File) {
            setCohort({ ...cohort, csv: file })

            return false
        },
        accept: '.csv',
    }

    return (
        <div className="mb">
            <Row gutter={16}>
                <Col>
                    <h3 className="l3">General</h3>
                </Col>
            </Row>
            <Row gutter={16}>
                <Col md={14}>
                    <CohortNameInput input={cohort.name} onChange={onNameChange} />
                </Col>
                <Col md={10}>
                    <CohortTypeSelector type={cohort.is_static ? STATIC : DYNAMIC} onTypeChange={onTypeChange} />
                </Col>
            </Row>
            <Row gutter={16} className="mt">
                <Col span={24}>
                    <CohortDescriptionInput description={cohort.description} onChange={onDescriptionChange} />
                </Col>
            </Row>
            {cohort.id && cohort.id !== 'new' && <CohortDetailsRow cohort={cohort} />}
            <Divider />
            {cohort.is_static ? (
                <div>
                    <h3 className="l3">Add Users</h3>
                    <span>
                        Drop a <pre style={{ display: 'inline' }}>.csv</pre> file here to add users to your cohort
                    </span>
                    <Dragger {...staticCSVDraggerProps} className="cohort-csv-dragger">
                        <p className="ant-upload-drag-icon">
                            <InboxOutlined />
                        </p>
                        <div>
                            <p className="ant-upload-text">Click or drag file to this area to upload</p>
                            <p className="ant-upload-hint">
                                The CSV file only requires a single column with the user’s distinct ID.
                            </p>
                        </div>
                    </Dragger>
                </div>
            ) : (
                <CohortMatchingCriteriaSection
                    onCriteriaChange={onCriteriaChange}
                    cohort={cohort}
                    onAddGroup={onAddGroup}
                    onRemoveGroup={onRemoveGroup}
                />
            )}

            {cohort.id !== 'new' && (
                <>
                    <Divider />
                    <div>
                        <h3 className="l3">Matched Users</h3>
                        <span>List of users that currently match the criteria defined</span>
                        <div style={{ marginTop: 15 }}>
                            <Persons cohort={cohort} key={lastSavedAt} />
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}

export function CohortV2Footer(props: { cohort: CohortType }): JSX.Element {
    const logic = cohortLogic(props)
    const { cohort } = useValues(logic)
    const { saveCohort } = useActions(logic)

    return (
        <Row style={{ display: 'flex' }}>
            <Button type="link" danger icon={<DeleteOutlined />}>
                Delete cohort
            </Button>
            <div style={{ flexGrow: 1, textAlign: 'right' }}>
                <Button
                    disabled={!cohort.name}
                    type="primary"
                    htmlType="submit"
                    data-attr="save-cohort"
                    onClick={saveCohort}
                    style={{ float: 'right' }}
                    icon={<SaveOutlined />}
                >
                    Save cohort
                </Button>
            </div>
        </Row>
    )
}
